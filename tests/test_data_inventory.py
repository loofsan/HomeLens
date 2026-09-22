from pathlib import Path

import pytest
from homelens.data.inventory import inspect_raw_data


def test_inventory_reports_quality_and_zip_coverage(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "redfin_data.csv").write_text(
        "SOLD DATE,PRICE,BEDS,BATHS,SQUARE FEET,YEAR BUILT,PROPERTY TYPE,"
        "ZIP OR POSTAL CODE,MLS#\n"
        "2024-01-02,250000,3,2,1200,1990,Single Family Residential,01234.0,A1\n"
        "2024-01-02,250000,3,2,1200,1990,Single Family Residential,01234.0,A1\n"
        ",300000,4,3,1500,2000,Townhouse,99999,\n",
        encoding="utf-8",
    )
    (raw_dir / "zipcode_saleprice.csv").write_text(
        "RegionName,RegionType,State,2024-01-01,2024-02-01\n01234,zip,NC,200000,\n",
        encoding="utf-8",
    )

    report = inspect_raw_data(raw_dir)

    sales = report["redfin_data.csv"]
    assert sales["rows"] == 3
    assert sales["duplicate_rows"] == 1
    assert sales["duplicate_nonblank_mls_ids"] == 1
    assert sales["missing_by_column"]["SOLD DATE"] == 1
    assert sales["sold_date_range"] == ["2024-01-02", "2024-01-02"]
    assert sales["target_column"] == "PRICE"
    assert sales["rows_with_sale_date_price_and_features"] == 2
    assert len(sales["sha256"]) == 64
    assert sales["missing_expected_columns"] == []

    prices = report["zipcode_saleprice.csv"]
    assert prices["rows"] == 1
    assert prices["monthly_columns"] == 2
    assert prices["month_range"] == ["2024-01-01", "2024-02-01"]
    assert prices["missing_monthly_values"] == 1
    assert prices["missing_month_columns"] == []
    assert prices["zip_overlap"] == ["01234"]
    assert prices["home_zips_without_series"] == ["99999"]
    assert prices["sale_rows_with_series_zip"] == 2


def test_inventory_rejects_missing_expected_columns(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "redfin_data.csv").write_text(
        "SOLD DATE,PRICE\n2024-01-02,250000\n", encoding="utf-8"
    )
    (raw_dir / "zipcode_saleprice.csv").write_text(
        "RegionName,RegionType,State,2024-01-01\n01234,zip,NC,200000\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="redfin_data.csv missing expected columns"):
        inspect_raw_data(raw_dir)


def test_inventory_rejects_duplicate_headers(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "redfin_data.csv").write_text(
        "PRICE,PRICE\n250000,250000\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="duplicate headers: PRICE"):
        inspect_raw_data(raw_dir)
