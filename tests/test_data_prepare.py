import json
from datetime import date
from pathlib import Path

import pytest
from homelens.data.prepare import prepare_sales


def test_prepare_sales_filters_and_splits_without_target_leakage(
    tmp_path: Path,
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    header = (
        "SALE TYPE,SOLD DATE,PRICE,BEDS,BATHS,SQUARE FEET,YEAR BUILT,"
        "PROPERTY TYPE,ZIP OR POSTAL CODE,MLS#,STATE OR PROVINCE,$/SQUARE FEET\n"
    )
    rows = [
        "PAST SALE,2023-06-01,250000,3,2,1200,1990,"
        "Single Family Residential,27703.0,A1,NC,208",
        "PAST SALE,2024-06-01,350000,3,2,1200,1990,"
        "Single Family Residential,27703.0,A1,NC,292",
        "PAST SALE,2025-02-01,500000,2,1,900,2000,Condo/Co-op,27705,B2,NC,556",
        "PAST SALE,2023-06-01,250000,3,2,1200,1990,"
        "Single Family Residential,27703.0,A1,NC,208",
        "PAST SALE,2023-06-01,1,0,0,1,1990,Vacant Land,27703,C3,NC,1",
        "PAST SALE,not-a-date,300000,3,2,1200,1990,Townhouse,27703,D4,NC,250",
        "PAST SALE,2023-06-01,0,3,2,1200,1990,Townhouse,27703,E5,NC,0",
        "PAST SALE,2023-06-01,300000,3,2,,1990,Townhouse,27703,F6,NC,250",
        "PAST SALE,2023-06-01,300000,3,2,2,1990,Townhouse,27703,G7,NC,250",
        "PAST SALE,2023-06-01,300000,3,2,1200,2025,Townhouse,27703,H8,NC,250",
        "PAST SALE,2023-06-01,300000,3,2,1200,1990,Townhouse,ABCDE,I9,NC,250",
        "PAST SALE,2023-06-01,300000,3,2,1200,1990,Townhouse,27703,J10,SC,250",
        "PAST SALE,2023-06-01,300000,3,2,1200,1990,"
        "Multi-Family (2-4 Unit),27703,K11,NC,250",
        "PAST SALE,2023-06-01,300000,3,2,1200,1990,Townhouse,27517,L12,NC,250",
        "PAST SALE,2023-06-01,300000,3,2,inf,1990,Townhouse,27703,M13,NC,250",
    ]
    (raw_dir / "redfin_data.csv").write_text(
        header + "\n".join(rows) + "\n", encoding="utf-8"
    )

    prepared, audit = prepare_sales(raw_dir)

    assert len(prepared) == 3
    assert prepared["split"].tolist() == ["train", "validation", "test"]
    assert prepared["zip"].tolist() == ["27703", "27703", "27705"]
    assert prepared["price_usd"].tolist() == [250000, 350000, 500000]
    assert "$/SQUARE FEET" not in prepared.columns
    assert "MLS#" not in prepared.columns
    assert audit["split_counts"] == {"train": 1, "validation": 1, "test": 1}
    assert audit["rejected_rows_by_stage"] == {
        "exact_duplicates": 1,
        "not_past_sale": 0,
        "missing_or_invalid_sale_date": 1,
        "missing_invalid_or_nonpositive_price": 1,
        "outside_initial_residential_types": 2,
        "outside_north_carolina": 1,
        "missing_core_features": 1,
        "invalid_zip_format": 1,
        "outside_study_zips": 1,
        "implausible_core_features": 3,
    }
    assert audit["rules"]["county_boundary_validated"] is False
    assert audit["source_rows"] == len(prepared) + sum(
        audit["rejected_rows_by_stage"].values()
    )
    assert len(audit["source_identity"]["sha256"]) == 64


def test_prepare_sales_validates_temporal_boundaries(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="validation start must be before test start"):
        prepare_sales(tmp_path, date(2025, 1, 1), date(2024, 1, 1))


def test_county_verified_cohort_keeps_boundary_points_and_audits_exclusions(
    tmp_path: Path,
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "durham_county_boundary.geojson").write_text(
        json.dumps(
            {
                "type": "Feature",
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
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    header = (
        "SALE TYPE,SOLD DATE,PRICE,BEDS,BATHS,SQUARE FEET,YEAR BUILT,"
        "PROPERTY TYPE,ZIP OR POSTAL CODE,MLS#,STATE OR PROVINCE,LATITUDE,LONGITUDE\n"
    )
    rows = [
        "PAST SALE,2023-06-01,250000,3,2,1200,1990,Townhouse,27703,A1,NC,36,-79",
        "PAST SALE,2024-06-01,350000,3,2,1200,1990,Townhouse,27703,A2,NC,36,-79",
        "PAST SALE,2025-02-01,450000,3,2,1200,1990,Townhouse,27703,A3,NC,36,-79",
        "PAST SALE,2024-06-01,350000,3,2,1200,1990,Townhouse,27703,A4,NC,36,-79.2",
        "PAST SALE,2024-06-01,350000,3,2,1200,1990,Townhouse,27703,A5,NC,36,-79.5",
        "PAST SALE,2024-06-01,350000,3,2,1200,1990,Townhouse,27703,A6,NC,,-79",
        "PAST SALE,2024-06-01,350000,3,2,1200,1990,Townhouse,27517,A7,NC,36,-79",
    ]
    (raw_dir / "redfin_data.csv").write_text(
        header + "\n".join(rows) + "\n", encoding="utf-8"
    )

    original, original_audit = prepare_sales(raw_dir)
    verified, audit = prepare_sales(raw_dir, county_verified_study_zips=True)

    assert len(original) == 6
    assert original_audit["rules"]["county_boundary_validated"] is False
    assert len(verified) == 4
    assert audit["split_counts"] == {"train": 1, "validation": 2, "test": 1}
    assert audit["rejected_rows_by_stage"]["unusable_coordinates"] == 1
    assert audit["rejected_rows_by_stage"]["outside_county"] == 1
    assert audit["rejected_rows_by_stage"]["outside_study_zips"] == 1
    assert audit["rules"]["county_boundary_validated"] is True
    assert audit["rules"]["county_boundary_points_count_as_inside"] is True
    assert len(audit["boundary_source_identity"]["sha256"]) == 64
