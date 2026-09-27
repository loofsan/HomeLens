"""ZCTA demographic profiles stay sourced, explicit about gaps, and optional."""

from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path

import pytest
from flask import Flask
from homelens import create_app
from homelens.data.acs_zcta import main, prepare_zcta_profiles
from homelens.data.property_catalog import write_catalog
from homelens.domain.property import HistoricalSale

NBSP = "\N{NO-BREAK SPACE}"
GEOGRAPHIES = ("ZCTA5 27703", "ZCTA5 27705", "Durham County, North Carolina")
MEASURES = ("Estimate", "Margin of Error", "Percent", "Percent Margin of Error")

DP05_ROWS = [
    ("SEX AND AGE", 0, None),
    ("Total population", 4, ("51,000", "±1,900", "51,000", "(X)")),
    ("Median age (years)", 8, ("34.2", "±0.8", "(X)", "(X)")),
    ("Under 18 years", 8, ("11,200", "±700", "22.0%", "±1.2")),
    ("65 years and over", 8, ("6,100", "±500", "12.0%", "±0.9")),
    ("65 years and over", 8, ("6,100", "±500", "6,100", "(X)")),
    ("RACE", 0, None),
    ("Two or More Races", 8, ("4,000", "±600", "7.8%", "±1.1")),
    ("HISPANIC OR LATINO AND RACE", 0, None),
    ("Total population", 4, ("51,000", "±1,900", "51,000", "(X)")),
    ("Hispanic or Latino (of any race)", 8, ("7,650", "±900", "15.0%", "±1.7")),
    ("Not Hispanic or Latino", 8, ("43,350", "±1,800", "85.0%", "±1.7")),
    ("White alone", 12, ("17,850", "±1,100", "35.0%", "±2.0")),
    ("Black or African American alone", 12, ("20,400", "±1,300", "40.0%", "±2.2")),
    ("American Indian and Alaska Native alone", 12, ("100", "±90", "0.2%", "±0.2")),
    ("Asian alone", 12, ("3,060", "±500", "6.0%", "±1.0")),
    ("Native Hawaiian and Other Pacific Islander alone", 12, ("-", "**", "-", "**")),
    ("Some Other Race alone", 12, ("240", "±150", "0.5%", "±0.3")),
    ("Two or More Races", 12, ("1,700", "±400", "3.3%", "±0.8")),
]
DP03_ROWS = [
    ("EMPLOYMENT STATUS", 0, None),
    ("Population 16 years and over", 4, ("40,000", "±1,000", "40,000", "(X)")),
    ("INCOME AND BENEFITS (IN 2024 INFLATION-ADJUSTED DOLLARS)", 0, None),
    ("Total households", 4, ("20,000", "±600", "20,000", "(X)")),
    ("Median household income (dollars)", 8, ("72,500", "±4,100", "(X)", "(X)")),
    ("Mean household income (dollars)", 8, ("91,000", "±5,000", "(X)", "(X)")),
]


def _write(
    path: Path,
    rows: list[tuple[str, int, tuple[str, str, str, str] | None]],
    geographies: tuple[str, ...] = GEOGRAPHIES,
    overrides: dict[tuple[str, str], tuple[str, str, str, str]] | None = None,
) -> None:
    header = ["Label (Grouping)"] + [
        f"{geography}!!{measure}" for geography in geographies for measure in MEASURES
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.writer(target, quoting=csv.QUOTE_ALL)
        writer.writerow(header)
        for label, indent, values in rows:
            row = [NBSP * indent + label]
            for geography in geographies:
                cells = (overrides or {}).get((geography, label), values)
                row.extend(cells if cells is not None else ("", "", "", ""))
            writer.writerow(row)


def _raw(tmp_path: Path, year: str = "2024") -> Path:
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    _write(raw / f"ACSDP5Y{year}.DP05-2026-09-27T010203.csv", DP05_ROWS)
    _write(
        raw / f"ACSDP5Y{year}.DP03-2026-09-27T010203.csv",
        DP03_ROWS,
        overrides={
            ("ZCTA5 27705", "Median household income (dollars)"): (
                "250,000+",
                "***",
                "(X)",
                "(X)",
            )
        },
    )
    return raw


def test_profiles_parse_selected_metrics_with_margins_and_gaps(tmp_path: Path) -> None:
    report = prepare_zcta_profiles(_raw(tmp_path))
    assert report["dataset"] == "2020-2024 ACS 5-Year Data Profiles DP05 and DP03"
    assert report["period"] == "2020-2024"
    assert report["zctas"] == ["27703", "27705"]
    assert report["county_included"] is True
    assert len(report["source_files"]) == 2
    assert all(len(item["identity"]["sha256"]) == 64 for item in report["source_files"])

    profile = report["profiles"]["27703"]
    assert profile["total_population"]["estimate"] == {
        "value": 51000,
        "status": "available",
    }
    assert profile["total_population"]["estimate_margin_of_error"]["value"] == 1900
    assert profile["median_age_years"]["estimate"]["value"] == 34.2
    assert profile["age_65_and_over"]["percent"]["value"] == 12.0
    assert profile["black_alone_not_hispanic"]["percent"]["value"] == 40.0
    assert profile["two_or_more_races_not_hispanic"]["percent"]["value"] == 3.3
    assert profile["median_household_income_usd"]["estimate"]["value"] == 72500
    assert profile["pacific_islander_alone_not_hispanic"]["percent"] == {
        "value": None,
        "status": "unavailable",
        "source_token": "-",
    }
    top = report["profiles"]["27705"]["median_household_income_usd"]
    assert top["estimate"] == {
        "value": 250000,
        "status": "top_coded",
        "source_token": "250,000+",
    }
    assert top["estimate_margin_of_error"]["status"] == "unavailable"


def test_latest_complete_year_is_used(tmp_path: Path) -> None:
    raw = _raw(tmp_path, "2023")
    _write(raw / "ACSDP5Y2024.DP05-2026-09-27T010203.csv", DP05_ROWS)
    assert prepare_zcta_profiles(raw)["period"] == "2019-2023"


@pytest.mark.parametrize("missing", ["DP03", "DP05"])
def test_both_tables_are_required(tmp_path: Path, missing: str) -> None:
    raw = _raw(tmp_path)
    next(raw.glob(f"*.{missing}-*.csv")).unlink()
    with pytest.raises(ValueError, match="same year"):
        prepare_zcta_profiles(raw)


def test_duplicate_geography_and_unknown_tokens_are_refused(tmp_path: Path) -> None:
    raw = _raw(tmp_path)
    _write(raw / "ACSDP5Y2024.DP05-second.csv", DP05_ROWS, geographies=("ZCTA5 27703",))
    with pytest.raises(ValueError, match="more than one"):
        prepare_zcta_profiles(raw)

    other = _raw(tmp_path / "other")
    _write(
        next(other.glob("*.DP03-*.csv")),
        DP03_ROWS,
        overrides={
            ("ZCTA5 27703", "Median household income (dollars)"): (
                "about 70k",
                "",
                "(X)",
                "(X)",
            )
        },
    )
    with pytest.raises(ValueError, match="Unexpected ACS value"):
        prepare_zcta_profiles(other)


def test_command_writes_aggregate_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _raw(tmp_path)
    output = tmp_path / "processed/acs_zcta_profiles.json"
    monkeypatch.setattr(
        sys, "argv", ["acs_zcta", "--raw-dir", str(raw), "--output", str(output)]
    )
    assert main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))["zctas"] == [
        "27703",
        "27705",
    ]


def _app(tmp_path: Path, profiles: Path | None) -> Flask:
    database = tmp_path / "sales.sqlite3"
    base = {
        "sale_date": date(2024, 6, 1),
        "sold_price_usd": 350000.0,
        "beds": 3.0,
        "baths": 2.0,
        "square_feet": 1200.0,
        "year_built": 1990,
        "property_type": "Townhouse",
        "address": "1 Main St",
        "city": "Durham",
        "state": "NC",
        "latitude": 36.0,
        "longitude": -79.0,
        "source_url": None,
    }
    write_catalog(
        database,
        [
            HistoricalSale(id="sale_" + "a" * 32, zip="27703", **base),  # type: ignore[arg-type]
            HistoricalSale(id="sale_" + "b" * 32, zip="27560", **base),  # type: ignore[arg-type]
        ],
        {
            "imported_rows": 2,
            "source_identity": {"sha256": "a" * 64},
            "boundary_source_identity": {"sha256": "b" * 64},
            "sale_date_range": ["2024-06-01", "2024-06-01"],
        },
    )
    return create_app(
        {
            "TESTING": True,
            "PROPERTY_CATALOG_PATH": database,
            "ACS_ZCTA_PROFILES_PATH": profiles or tmp_path / "missing.json",
        }
    )


def test_api_serves_profile_for_sale_zip_with_scope(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles.json"
    profiles.write_text(json.dumps(prepare_zcta_profiles(_raw(tmp_path))))
    client = _app(tmp_path, profiles).test_client()

    response = client.get(f"/api/properties/sale_{'a' * 32}/demographics")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "available"
    assert payload["geography"]["kind"] == "zcta"
    assert payload["geography"]["id"] == "27703"
    assert "approximate" in payload["geography"]["note"]
    assert payload["period"] == "2020-2024"
    assert payload["metrics"]["median_household_income_usd"]["estimate"]["value"] == (
        72500
    )

    missing_zcta = client.get(f"/api/properties/sale_{'b' * 32}/demographics")
    assert missing_zcta.status_code == 200
    assert missing_zcta.get_json()["status"] == "unavailable"
    assert missing_zcta.get_json()["reason"] == "zcta_not_prepared"
    assert "metrics" not in missing_zcta.get_json()

    assert client.get("/api/properties/unknown/demographics").status_code == 404


def test_api_reports_unprepared_profiles_without_breaking_search(
    tmp_path: Path,
) -> None:
    client = _app(tmp_path, None).test_client()
    response = client.get(f"/api/properties/sale_{'a' * 32}/demographics")
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "demographics_unavailable"
    assert client.get("/api/properties").status_code == 200
    assert client.get("/api/health").status_code == 200
