import json
from pathlib import Path

import pytest
from homelens.data.geography import audit_geography


def _boundary() -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"ID": 1},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-79.2, 35.8],
                            [-78.8, 35.8],
                            [-78.8, 36.2],
                            [-79.2, 36.2],
                            [-79.2, 35.8],
                        ]
                    ],
                },
            }
        ],
    }


def test_geography_audit_compares_zip_rule_with_polygon(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "durham_county_boundary.geojson").write_text(
        json.dumps(_boundary()), encoding="utf-8"
    )
    header = (
        "SALE TYPE,SOLD DATE,PRICE,BEDS,BATHS,SQUARE FEET,YEAR BUILT,"
        "PROPERTY TYPE,ZIP OR POSTAL CODE,MLS#,LATITUDE,LONGITUDE\n"
    )
    rows = [
        "PAST SALE,2024-01-01,250000,3,2,1200,1990,Townhouse,27703.0,A1,36,-79",
        "PAST SALE,2024-01-01,250000,3,2,1200,1990,Townhouse,27517,B2,36,-79",
        "PAST SALE,2024-01-01,250000,3,2,1200,1990,Townhouse,27703,C3,36.5,-79",
        "PAST SALE,2024-01-01,250000,3,2,1200,1990,Townhouse,27517,D4,36.5,-79",
        "PAST SALE,2024-01-01,250000,3,2,1200,1990,Townhouse,27703,E5,35.8,-79",
        "PAST SALE,2024-01-01,250000,3,2,1200,1990,Townhouse,27703,F6,,-79",
        "PAST SALE,2024-01-01,250000,3,2,1200,1990,Townhouse,27703.0,A1,36,-79",
        "FOR SALE,2024-01-01,250000,3,2,1200,1990,Townhouse,27703,G7,36,-79",
        "PAST SALE,not-a-date,250000,3,2,1200,1990,Townhouse,27703,H8,36,-79",
    ]
    (raw_dir / "redfin_data.csv").write_text(header + "\n".join(rows) + "\n")

    report = audit_geography(raw_dir)

    assert report["source_rows"] == 9
    assert report["exact_duplicate_rows"] == 1
    assert report["historical_sale_rows"] == 6
    assert report["unusable_coordinate_rows"] == 1
    assert report["compared_rows"] == 5
    assert report["in_county_rows"] == 3
    assert report["outside_county_rows"] == 2
    assert report["zip_boundary_comparison"] == {
        "in_county_in_study_zip": 2,
        "in_county_outside_study_zip": 1,
        "outside_county_in_study_zip": 1,
        "outside_county_outside_study_zip": 1,
    }
    assert report["in_county_outside_study_zip_by_zip"] == {"27517": 1}
    assert report["outside_county_in_study_zip_by_zip"] == {"27703": 1}
    assert report["boundary_points_count_as_inside"] is True
    assert sum(report["zip_boundary_comparison"].values()) == report["compared_rows"]


def test_geography_audit_rejects_projected_boundary(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    boundary = _boundary()
    boundary["features"] = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [2000000, 800000],
                        [2100000, 800000],
                        [2100000, 900000],
                        [2000000, 800000],
                    ]
                ],
            },
        }
    ]
    (raw_dir / "durham_county_boundary.geojson").write_text(
        json.dumps(boundary), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="WGS84 lon/lat coordinates"):
        audit_geography(raw_dir)


def test_geography_audit_requires_one_boundary_feature(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    boundary = _boundary()
    boundary["features"] = []
    (raw_dir / "durham_county_boundary.geojson").write_text(
        json.dumps(boundary), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="exactly one county feature"):
        audit_geography(raw_dir)
