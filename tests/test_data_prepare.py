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
