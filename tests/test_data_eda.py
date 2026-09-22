from pathlib import Path

import pytest
from homelens.data.eda import profile_raw_data


def test_eda_profiles_historical_sales_and_unverified_zip_series(
    tmp_path: Path,
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "redfin_data.csv").write_text(
        "SALE TYPE,SOLD DATE,PRICE,BEDS,BATHS,SQUARE FEET,YEAR BUILT,"
        "PROPERTY TYPE,ZIP OR POSTAL CODE,MLS#\n"
        "PAST SALE,2024-01-02,250000,3,2,1200,1990,Single Family,01234.0,A1\n"
        "PAST SALE,2024-01-02,250000,3,2,1200,1990,Single Family,01234.0,A1\n"
        "PAST SALE,2024-02-02,350000,4,3,2000,2030,Townhouse,99999,B2\n"
        "PAST SALE,,100000,2,1,800,1980,Single Family,01234,C3\n"
        "FOR SALE,2024-04-02,900000,5,4,3000,2020,Townhouse,01234,D4\n"
        "PAST SALE,2024-03-02,0,2,1,900,1985,Single Family,01234,E5\n"
        "PAST SALE,2025-01-02,500000,3,2,,2005,Single Family,01234,F6\n",
        encoding="utf-8",
    )
    (raw_dir / "zipcode_saleprice.csv").write_text(
        "RegionName,RegionType,State,2024-01-01,2024-02-01\n"
        "01234,zip,NC,100,110\n"
        "99999,zip,NC,200,\n",
        encoding="utf-8",
    )

    report = profile_raw_data(raw_dir)

    sales = report["sales"]
    assert sales["source_rows"] == 7
    assert sales["exact_duplicate_rows"] == 1
    assert sales["past_sale_rows"] == 5
    assert sales["historical_sale_rows"] == 3
    assert sales["complete_core_feature_rows"] == 2
    assert sales["missing_or_invalid_sale_date_rows"] == 1
    assert sales["missing_invalid_or_nonpositive_price_rows"] == 1
    assert sales["missing_core_features_in_historical_sales"]["SQUARE FEET"] == 1
    assert sales["price_usd"]["median"] == 350000
    assert sales["sales_by_year"]["2024"] == {
        "count": 2,
        "median_price_usd": 300000,
    }
    assert sales["sales_by_zip"]["01234"]["count"] == 2
    assert sales["historical_sale_rows_with_series_zip"] == 3
    assert sales["anomalies_in_historical_sales"]["year_built_after_sale"] == 1

    history = report["zip_history"]
    assert history["series_metric"] == "unverified"
    assert history["month_range"] == ["2024-01-01", "2024-02-01"]
    assert history["regions"][0]["change_pct"] == 10
    assert history["regions"][1]["missing_months"] == 1
    assert report["modeling_cautions"]["target_derived_field"] == "$/SQUARE FEET"


def test_eda_handles_empty_numeric_distribution(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "redfin_data.csv").write_text(
        "SALE TYPE,SOLD DATE,PRICE,BEDS,BATHS,SQUARE FEET,YEAR BUILT,"
        "PROPERTY TYPE,ZIP OR POSTAL CODE,MLS#\n"
        "PAST SALE,2024-01-02,100000,,,,,Single Family,01234,A1\n",
        encoding="utf-8",
    )
    (raw_dir / "zipcode_saleprice.csv").write_text(
        "RegionName,RegionType,State,2024-01-01\n01234,zip,NC,100\n",
        encoding="utf-8",
    )

    report = profile_raw_data(raw_dir)

    assert report["sales"]["numeric_features"]["BEDS"]["median"] is None
    assert report["sales"]["complete_core_feature_rows"] == 0


def test_eda_rejects_series_without_month_columns(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "redfin_data.csv").write_text(
        "SALE TYPE,SOLD DATE,PRICE,BEDS,BATHS,SQUARE FEET,YEAR BUILT,"
        "PROPERTY TYPE,ZIP OR POSTAL CODE,MLS#\n",
        encoding="utf-8",
    )
    (raw_dir / "zipcode_saleprice.csv").write_text(
        "RegionName,RegionType,State\n01234,zip,NC\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="no monthly date columns"):
        profile_raw_data(raw_dir)
