"""ZIP index adjustments stay labeled, scoped, and forecast-free."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest
from flask import Flask
from homelens import create_app
from homelens.data.property_catalog import write_catalog
from homelens.data.zip_index import main, prepare_zip_index
from homelens.domain.property import HistoricalSale

HEADER = (
    "RegionID,SizeRank,RegionName,RegionType,StateName,State,City,Metro,CountyName,"
    "2024-01-01,2024-02-01,2024-03-01,2024-04-01\n"
)


def _raw(tmp_path: Path, rows: str | None = None) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "zipcode_saleprice.csv").write_text(
        HEADER
        + (
            rows
            or (
                '1,1,27703,zip,NC,NC,Durham,"Durham-Chapel Hill, NC",Durham County,'
                "400000,404000,,410000\n"
                '2,2,27705,zip,NC,NC,Durham,"Durham-Chapel Hill, NC",Durham County,'
                "500000,495000,490000,485000\n"
            )
        ),
        encoding="utf-8",
    )
    return raw


def test_index_preparation_keeps_gaps_and_forecast_absent(tmp_path: Path) -> None:
    report = prepare_zip_index(_raw(tmp_path))
    assert report["months"] == ["2024-01", "2024-02", "2024-03", "2024-04"]
    assert report["zips"]["27703"] == [400000.0, 404000.0, None, 410000.0]
    assert report["missing_values"] == {"27703": 1}
    assert report["variant_confirmed"] is False
    assert report["forecast"] is None
    assert "no-change" in report["forecast_note"]
    assert len(report["source_identity"]["sha256"]) == 64


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            "1,1,27703,zip,NC,NC,Durham,x,Durham County,400000,0,1,2\n",
            "non-positive",
        ),
        (
            "1,1,27703,zip,NC,NC,Durham,x,Durham County,1,2,3,4\n"
            "2,1,27703,zip,NC,NC,Durham,x,Durham County,1,2,3,4\n",
            "repeated",
        ),
    ],
)
def test_index_preparation_refuses_bad_rows(
    tmp_path: Path, rows: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        prepare_zip_index(_raw(tmp_path, rows))


def _sale(letter: str, zip_code: str, sold: date) -> HistoricalSale:
    return HistoricalSale(
        id="sale_" + letter * 32,
        sale_date=sold,
        sold_price_usd=300000.0,
        beds=3.0,
        baths=2.0,
        square_feet=1200.0,
        year_built=1990,
        property_type="Townhouse",
        address="1 Main St",
        city="Durham",
        state="NC",
        zip=zip_code,
        latitude=36.0,
        longitude=-79.0,
        source_url=None,
    )


def _app(tmp_path: Path, prepared: bool = True) -> Flask:
    database = tmp_path / "sales.sqlite3"
    write_catalog(
        database,
        [
            _sale("a", "27703", date(2024, 1, 20)),
            _sale("b", "27705", date(2024, 2, 3)),
            _sale("c", "27560", date(2024, 2, 3)),
            _sale("d", "27703", date(2024, 5, 1)),
            _sale("e", "27703", date(2024, 3, 9)),
        ],
        {
            "imported_rows": 5,
            "source_identity": {"sha256": "a" * 64},
            "boundary_source_identity": {"sha256": "b" * 64},
            "sale_date_range": ["2024-01-20", "2024-05-01"],
        },
    )
    index = tmp_path / "zip_value_index.json"
    if prepared:
        index.write_text(json.dumps(prepare_zip_index(_raw(tmp_path))))
    return create_app(
        {
            "TESTING": True,
            "PROPERTY_CATALOG_PATH": database,
            "ZIP_VALUE_INDEX_PATH": index,
        }
    )


def test_api_adjusts_sale_price_along_zip_index(tmp_path: Path) -> None:
    client = _app(tmp_path).test_client()
    payload = client.get(f"/api/properties/sale_{'a' * 32}/value-trend").get_json()
    assert payload["status"] == "available"
    assert payload["sale_month"] == "2024-01"
    assert payload["latest_month"] == "2024-04"
    assert payload["latest_adjusted_value_usd"] == 307500
    assert payload["index_change_pct"] == 2.5
    assert [point["month"] for point in payload["points"]] == [
        "2024-01",
        "2024-02",
        "2024-04",
    ]
    assert payload["points"][0]["adjusted_value_usd"] == 300000
    assert payload["forecast"] is None
    assert "not an appraisal" in payload["method_note"]
    assert payload["variant_confirmed"] is False

    falling = client.get(f"/api/properties/sale_{'b' * 32}/value-trend").get_json()
    assert falling["index_change_pct"] == pytest.approx(-2.0)
    assert falling["latest_adjusted_value_usd"] == 293939


@pytest.mark.parametrize(
    ("letter", "reason"),
    [("c", "zip_not_in_index"), ("d", "sale_after_index"), ("e", "index_missing")],
)
def test_api_reports_unsupported_sales(
    tmp_path: Path, letter: str, reason: str
) -> None:
    payload = (
        _app(tmp_path)
        .test_client()
        .get(f"/api/properties/sale_{letter * 32}/value-trend")
        .get_json()
    )
    assert payload["status"] == "unavailable"
    assert payload["reason"] == reason
    assert "points" not in payload


def test_api_reports_unprepared_index_and_missing_sale(tmp_path: Path) -> None:
    client = _app(tmp_path, prepared=False).test_client()
    response = client.get(f"/api/properties/sale_{'a' * 32}/value-trend")
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "value_trend_unavailable"
    assert client.get("/api/properties/unknown/value-trend").status_code == 404
    assert client.get("/api/health").status_code == 200


def test_command_writes_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "out/zip_value_index.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["zip_index", "--raw-dir", str(_raw(tmp_path)), "--output", str(output)],
    )
    assert main() == 0
    assert set(json.loads(output.read_text(encoding="utf-8"))["zips"]) == {
        "27703",
        "27705",
    }
