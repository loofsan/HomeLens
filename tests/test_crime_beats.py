"""Beat-level offense counts stay aggregate, scoped, and explicit about gaps."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from homelens import create_app
from homelens.data.crime_beats import aggregate_crime_by_beat, main


def _polygon(west: float, south: float, east: float, north: float) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [[west, south], [east, south], [east, north], [west, north], [west, south]]
        ],
    }


def _feature(
    code: int, district: str, geometry: dict[str, object]
) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {"LAWBEAT": code, "LAWDIST": district},
        "geometry": geometry,
    }


CRIME_ROWS = [
    # beat, code, date
    ("111", "13A ", "2022/01/01 00:00:00+00"),
    ("111", "120 ", "2023/06/01 10:00:00+00"),
    ("111", "23F ", "2023/06/02 10:00:00+00"),
    ("111", "9925", "2023/06/03 10:00:00+00"),
    ("112", "220 ", "2023/12/31 23:00:00+00"),
    ("112", "13B ", "2023/07/01 00:00:00+00"),
    ("112", "09A ", "2024/03/01 00:00:00+00"),
    ("", "13A ", "2023/01/05 00:00:00+00"),
    ("SSA", "240 ", "2023/01/05 00:00:00+00"),
    ("112", "240 ", "not a date"),
]


def _raw(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    (raw / "durham_police_beats.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    _feature(111, "D1", _polygon(-79.02, 35.98, -79.01, 35.99)),
                    _feature(111, "D1", _polygon(-79.01, 35.98, -79.0, 35.99)),
                    _feature(112, "D1", _polygon(-79.0, 35.98, -78.99, 35.99)),
                    _feature(299, "D2", _polygon(-78.99, 35.98, -78.98, 35.99)),
                ],
            }
        ),
        encoding="utf-8",
    )
    lines = ["OBJECTID,INCI_ID,DATE_REPT,UCR_CODE,BEAT,ADDRESS2"]
    for index, (beat, code, reported) in enumerate(CRIME_ROWS, start=1):
        lines.append(f"{index},{9000 + index},{reported},{code},{beat},1 SECRET ST")
    (raw / "DPD_Crime_(table_only).csv").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return raw


def test_aggregation_counts_categories_by_beat_and_year(tmp_path: Path) -> None:
    report = aggregate_crime_by_beat(_raw(tmp_path))
    metadata = report["metadata"]
    assert metadata["rows"] == {
        "total": 10,
        "in_category_scope": 8,
        "counted": 5,
        "missing_beat": 1,
        "unmatched_beat": 1,
        "unmatched_beat_by_code": {"SSA": 1},
        "invalid_report_date": 1,
    }
    assert [item["year"] for item in metadata["years"]] == [2022, 2023, 2024]
    assert [item["complete"] for item in metadata["years"]] == [True, True, False]
    assert metadata["years"][2]["last_report_date"] == "2024-03-01"
    assert metadata["years"][0]["first_report_date"] == "2022-01-01"
    assert metadata["categories"]["violent"]["codes"] == [
        "09A",
        "11A",
        "11B",
        "11C",
        "120",
        "13A",
    ]

    beats = {item["properties"]["beat"]: item for item in report["features"]}
    assert list(beats) == ["111", "112", "299"]
    first = beats["111"]["properties"]
    assert first["district"] == "D1"
    assert first["counts"]["2022"] == {"violent": 1, "property": 0}
    assert first["counts"]["2023"] == {"violent": 1, "property": 1}
    assert beats["111"]["geometry"]["type"] == "Polygon"
    assert first["area_km2"] == pytest.approx(
        2 * beats["112"]["properties"]["area_km2"]
    )
    assert beats["112"]["properties"]["counts"]["2024"] == {"violent": 1, "property": 0}
    assert beats["299"]["properties"]["has_records"] is False

    text = json.dumps(report)
    assert "SECRET" not in text
    assert "9001" not in text


def test_complete_years_need_full_calendar_coverage(tmp_path: Path) -> None:
    raw = _raw(tmp_path)
    crime = raw / "DPD_Crime_(table_only).csv"
    crime.write_text(
        crime.read_text(encoding="utf-8") + "99,1,2024/12/31 23:00:00+00,13B ,111,X\n",
        encoding="utf-8",
    )
    years = aggregate_crime_by_beat(raw)["metadata"]["years"]
    assert [item["complete"] for item in years] == [True, True, True]


def _app(tmp_path: Path, prepared: bool = True):  # type: ignore[no-untyped-def]
    path = tmp_path / "crime_beats.geojson"
    if prepared:
        path.write_text(json.dumps(aggregate_crime_by_beat(_raw(tmp_path))))
    return create_app(
        {
            "TESTING": True,
            "PROPERTY_CATALOG_PATH": tmp_path / "missing.sqlite3",
            "CRIME_BEATS_PATH": path,
        }
    )


def test_api_serves_one_year_and_category_with_scope(tmp_path: Path) -> None:
    client = _app(tmp_path).test_client()
    response = client.get("/api/crime/beats")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["type"] == "FeatureCollection"
    assert payload["metadata"]["year"] == 2023
    assert payload["metadata"]["category"] == "violent"
    assert payload["metadata"]["excluded_rows"] == {
        "missing_beat": 1,
        "unmatched_beat": 1,
        "invalid_report_date": 1,
    }
    assert any(
        "not complete crime statistics" in note for note in payload["metadata"]["notes"]
    )
    properties = {
        item["properties"]["beat"]: item["properties"] for item in payload["features"]
    }
    assert properties["111"]["count"] == 1
    assert properties["111"]["per_km2"] == round(1 / properties["111"]["area_km2"], 1)
    assert properties["112"]["count"] == 0
    assert properties["112"]["per_km2"] == 0
    assert properties["299"]["count"] is None
    assert properties["299"]["per_km2"] is None

    latest = client.get("/api/crime/beats?year=2024").get_json()
    assert latest["metadata"]["coverage"]["complete"] is False
    assert latest["features"][1]["properties"]["count"] == 1

    property_2023 = client.get(
        "/api/crime/beats?year=2023&category=property"
    ).get_json()
    counts = {
        item["properties"]["beat"]: item["properties"]["count"]
        for item in property_2023["features"]
    }
    assert counts == {"111": 1, "112": 1, "299": None}


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ("year=2019", "year"),
        ("year=24", "year"),
        ("category=all", "category"),
        ("zip=27703", "zip"),
    ],
)
def test_api_rejects_invalid_queries(tmp_path: Path, query: str, field: str) -> None:
    response = _app(tmp_path).test_client().get(f"/api/crime/beats?{query}")
    assert response.status_code == 400
    assert response.get_json()["error"]["field"] == field


def test_api_reports_unprepared_map_without_breaking_health(tmp_path: Path) -> None:
    client = _app(tmp_path, prepared=False).test_client()
    response = client.get("/api/crime/beats")
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "crime_map_unavailable"
    assert client.get("/api/health").status_code == 200


def test_command_writes_compact_geojson(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out/crime_beats.geojson"
    monkeypatch.setattr(
        sys,
        "argv",
        ["crime_beats", "--raw-dir", str(_raw(tmp_path)), "--output", str(output)],
    )
    assert main() == 0
    assert len(json.loads(output.read_text(encoding="utf-8"))["features"]) == 3
