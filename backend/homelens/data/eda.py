"""Generate a reproducible, read-only profile of the supplied housing CSVs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .inventory import (
    MONTH_COLUMN,
    REDFIN_COLUMNS,
    REDFIN_FEATURE_COLUMNS,
    ZIP_COLUMNS,
    _normalized_zips,
    _read_csv,
    _require_columns,
)


def _distribution(values: pd.Series[Any]) -> dict[str, int | float | None]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return {
            "count": 0,
            "min": None,
            "p05": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p95": None,
            "max": None,
        }
    quantiles = numeric.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    return {
        "count": len(numeric),
        "min": round(float(numeric.min()), 2),
        "p05": round(float(quantiles.loc[0.05]), 2),
        "p25": round(float(quantiles.loc[0.25]), 2),
        "median": round(float(quantiles.loc[0.5]), 2),
        "p75": round(float(quantiles.loc[0.75]), 2),
        "p95": round(float(quantiles.loc[0.95]), 2),
        "max": round(float(numeric.max()), 2),
    }


def _sales_profile(sales: pd.DataFrame, series_zips: set[str]) -> dict[str, Any]:
    unique = sales.drop_duplicates().copy()
    dates = pd.to_datetime(unique["SOLD DATE"], format="mixed", errors="coerce")
    prices = pd.to_numeric(unique["PRICE"], errors="coerce")
    past_sale = (
        unique["SALE TYPE"].astype("string").str.strip().eq("PAST SALE").fillna(False)
    )
    eligible = past_sale & dates.notna() & prices.gt(0)
    historical = unique.loc[eligible].copy()
    historical_dates = dates.loc[eligible]
    historical_prices = prices.loc[eligible]
    historical_zips = _normalized_zips(historical["ZIP OR POSTAL CODE"])
    core_complete = historical[list(REDFIN_FEATURE_COLUMNS)].notna().all(axis=1)

    by_year: dict[str, dict[str, int | float]] = {}
    for year, group in historical_prices.groupby(historical_dates.dt.year):
        by_year[str(year)] = {
            "count": len(group),
            "median_price_usd": round(float(group.median()), 2),
        }

    by_zip: dict[str, dict[str, int | float]] = {}
    for zip_code, group in historical_prices.groupby(historical_zips):
        if pd.isna(zip_code) or not str(zip_code).strip():
            continue
        by_zip[str(zip_code)] = {
            "count": len(group),
            "median_price_usd": round(float(group.median()), 2),
        }

    built = pd.to_numeric(historical["YEAR BUILT"], errors="coerce")
    sqft = pd.to_numeric(historical["SQUARE FEET"], errors="coerce")
    beds = pd.to_numeric(historical["BEDS"], errors="coerce")
    baths = pd.to_numeric(historical["BATHS"], errors="coerce")
    return {
        "source_rows": len(sales),
        "exact_duplicate_rows": len(sales) - len(unique),
        "unique_rows": len(unique),
        "past_sale_rows": int(past_sale.sum()),
        "historical_sale_rows": len(historical),
        "complete_core_feature_rows": int(core_complete.sum()),
        "missing_or_invalid_sale_date_rows": int(dates.isna().sum()),
        "missing_invalid_or_nonpositive_price_rows": int((~prices.gt(0)).sum()),
        "missing_core_features_in_historical_sales": {
            name: int(historical[name].isna().sum()) for name in REDFIN_FEATURE_COLUMNS
        },
        "price_usd": _distribution(historical_prices),
        "numeric_features": {
            "BEDS": _distribution(beds),
            "BATHS": _distribution(baths),
            "SQUARE FEET": _distribution(sqft),
            "YEAR BUILT": _distribution(built),
        },
        "anomalies_in_historical_sales": {
            "nonpositive_square_feet": int(sqft.le(0).sum()),
            "negative_beds": int(beds.lt(0).sum()),
            "negative_baths": int(baths.lt(0).sum()),
            "year_built_after_sale": int(built.gt(historical_dates.dt.year).sum()),
        },
        "property_type_counts": {
            str(name): int(count)
            for name, count in historical["PROPERTY TYPE"].value_counts().items()
        },
        "sales_by_year": by_year,
        "sales_by_zip": by_zip,
        "historical_sale_rows_with_series_zip": int(
            historical_zips.isin(series_zips).sum()
        ),
    }


def _series_profile(series: pd.DataFrame) -> dict[str, Any]:
    month_columns = sorted(
        name
        for name in series.columns
        if isinstance(name, str)
        and MONTH_COLUMN.fullmatch(name)
        and pd.notna(pd.to_datetime(name, format="%Y-%m-%d", errors="coerce"))
    )
    if not month_columns:
        raise ValueError("zipcode_saleprice.csv has no monthly date columns")

    regions: list[dict[str, Any]] = []
    for _, row in series.iterrows():
        values = pd.to_numeric(row[month_columns], errors="coerce")
        observed = values.dropna()
        first_month = str(observed.index[0]) if not observed.empty else None
        last_month = str(observed.index[-1]) if not observed.empty else None
        first_value = float(observed.iloc[0]) if not observed.empty else None
        last_value = float(observed.iloc[-1]) if not observed.empty else None
        change = (
            round((last_value / first_value - 1) * 100, 2)
            if first_value is not None and last_value is not None and first_value > 0
            else None
        )
        regions.append(
            {
                "zip": str(row["RegionName"]).strip(),
                "months_with_values": len(observed),
                "missing_months": len(month_columns) - len(observed),
                "nonpositive_values": int(values.le(0).sum()),
                "first_month": first_month,
                "last_month": last_month,
                "first_value": round(first_value, 2)
                if first_value is not None
                else None,
                "last_value": round(last_value, 2) if last_value is not None else None,
                "change_pct": change,
            }
        )
    return {
        "series_metric": "unverified",
        "region_count": len(series),
        "month_count": len(month_columns),
        "month_range": [month_columns[0], month_columns[-1]],
        "regions": regions,
    }


def profile_raw_data(raw_dir: Path) -> dict[str, Any]:
    sales_path = raw_dir / "redfin_data.csv"
    series_path = raw_dir / "zipcode_saleprice.csv"
    sales = _read_csv(sales_path, ("ZIP OR POSTAL CODE", "MLS#"))
    series = _read_csv(series_path, ("RegionName",))
    _require_columns(sales, sales_path, (*REDFIN_COLUMNS, "SALE TYPE"))
    _require_columns(series, series_path, ZIP_COLUMNS)
    series_zips = set(_normalized_zips(series["RegionName"]).dropna())
    return {
        "sales": _sales_profile(sales, series_zips),
        "zip_history": _series_profile(series),
        "modeling_cautions": {
            "target": "PRICE",
            "target_derived_field": "$/SQUARE FEET",
            "target_derived_field_action": "exclude from predictive features",
            "zip_series_metric": "unverified; do not label as observed median sales",
            "zip_series_temporal_rule": (
                "only use values available before the prediction date"
            ),
            "eligibility_note": (
                "historical_sale_rows is an EDA cohort, not a cleaned training set"
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile HomeLens raw CSV datasets")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/eda.json"))
    args = parser.parse_args()
    try:
        report = profile_raw_data(args.raw_dir)
    except (FileNotFoundError, ValueError, pd.errors.ParserError) as exc:
        parser.error(str(exc))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote EDA report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
