import json
from pathlib import Path

import pytest
from homelens.data.neighborhood_inventory import inspect_neighborhood_sources


def _sources(raw_dir: Path, geography: str = "United States") -> None:
    raw_dir.mkdir()
    (raw_dir / "DPD_Crime_(table_only).csv").write_text(
        "OBJECTID,INCI_ID,DATE_REPT,YEARSTAMP,MONTHSTAMP,DIST,BEAT,"
        "ADDRESS2,HOUR_REPT\n"
        "1,A1,2022/02/26 03:54:00+00,2022,2,3,314,PRIVATE ADDRESS,0354\n"
        "2,A1,2022/03/04 00:00:00+00,0,0,3,314,PRIVATE ADDRESS,0000\n",
        encoding="utf-8",
    )
    features = [
        {
            "type": "Feature",
            "geometry": None,
            "properties": {
                "OBJECTID": objectid,
                "INCI_ID": "A1",
                "DATE_REPT": reported,
                "YEARSTAMP": year,
                "MONTHSTAMP": month,
                "DIST": "3",
                "BEAT": "314",
                "ADDRESS2": "PRIVATE ADDRESS",
                "HOUR_REPT": hour,
            },
        }
        for objectid, reported, year, month, hour in (
            (1, "2022-02-26T03:54:00Z", 2022, 2, "0354"),
            (2, "2022-03-04T00:00:00Z", 0, 0, "0000"),
        )
    ]
    (raw_dir / "City_Crime_(External_Use).geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )
    (raw_dir / "ACSDP1Y2023.DP05-export.csv").write_text(
        f'Label (Grouping),"{geography}!!Estimate",'
        f'"{geography}!!Margin of Error"\n'
        "Total population,100,10\n",
        encoding="utf-8",
    )


def test_audit_detects_duplicate_nonspatial_exports_and_national_acs(
    tmp_path: Path,
) -> None:
    raw_dir = tmp_path / "raw"
    _sources(raw_dir)

    report = inspect_neighborhood_sources(raw_dir)

    assert report["crime_csv"]["rows"] == 2
    assert report["crime_csv"]["duplicate_incident_ids"] == 1
    assert report["crime_csv"]["yearstamp_zero_rows"] == 1
    assert report["crime_csv"]["reported_date_range"] == [
        "2022-02-26",
        "2022-03-04",
    ]
    assert report["crime_geojson"]["geometry_present_features"] == 0
    assert report["cross_export"]["same_nonspatial_records"] is True
    assert report["acs_dp05"]["geographies"] == ["United States"]
    assert report["readiness"] == {
        "crime_has_any_geometry": False,
        "durham_demographics_present": False,
        "zip_level_crime_supported": False,
    }
    assert "PRIVATE ADDRESS" not in json.dumps(report)


def test_audit_detects_durham_geography_and_property_mismatch(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _sources(raw_dir, geography="Durham County, North Carolina")
    geo_path = raw_dir / "City_Crime_(External_Use).geojson"
    document = json.loads(geo_path.read_text(encoding="utf-8"))
    document["features"][0]["properties"]["DIST"] = "4"
    document["crs"] = None
    geo_path.write_text(json.dumps(document), encoding="utf-8")

    report = inspect_neighborhood_sources(raw_dir)

    assert report["acs_dp05"]["durham_county_present"] is True
    assert report["cross_export"]["same_objectid_set"] is True
    assert report["cross_export"]["property_mismatches_by_column"]["DIST"] == 1
    assert report["cross_export"]["same_nonspatial_records"] is False
    assert report["crime_geojson"]["crs_name"] is None


def test_audit_does_not_call_duplicate_objectids_identical(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _sources(raw_dir)
    geo_path = raw_dir / "City_Crime_(External_Use).geojson"
    document = json.loads(geo_path.read_text(encoding="utf-8"))
    document["features"][1]["properties"]["OBJECTID"] = 1
    geo_path.write_text(json.dumps(document), encoding="utf-8")

    report = inspect_neighborhood_sources(raw_dir)

    assert report["crime_geojson"]["duplicate_objectids"] == 1
    assert report["cross_export"]["same_objectid_set"] is False
    assert report["cross_export"]["same_nonspatial_records"] is False


def test_audit_rejects_missing_acs_export(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _sources(raw_dir)
    (raw_dir / "ACSDP1Y2023.DP05-export.csv").unlink()

    with pytest.raises(ValueError, match="Expected one ACSDP1Y2023.DP05"):
        inspect_neighborhood_sources(raw_dir)
