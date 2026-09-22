"""Inspect raw source files without changing their contents."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

REDFIN_COLUMNS = (
    "SOLD DATE",
    "PRICE",
    "BEDS",
    "BATHS",
    "SQUARE FEET",
    "YEAR BUILT",
    "PROPERTY TYPE",
    "ZIP OR POSTAL CODE",
    "MLS#",
)
REDFIN_FEATURE_COLUMNS = (
    "BEDS",
    "BATHS",
    "SQUARE FEET",
    "YEAR BUILT",
    "PROPERTY TYPE",
    "ZIP OR POSTAL CODE",
)
ZIP_COLUMNS = ("RegionName", "RegionType", "State")
MONTH_COLUMN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def _read_csv(path: Path, text_columns: tuple[str, ...]) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Missing raw file: {path}")

    with path.open(encoding="utf-8-sig", newline="") as source:
        header = next(csv.reader(source), None)
    if not header:
        raise ValueError(f"{path.name} has no header")
    duplicates = sorted(name for name, count in Counter(header).items() if count > 1)
    if duplicates:
        raise ValueError(f"{path.name} duplicate headers: {', '.join(duplicates)}")

    text_types = {name: "string" for name in text_columns if name in header}
    return pd.read_csv(path, dtype=text_types, low_memory=False, encoding="utf-8-sig")


def _require_columns(
    frame: pd.DataFrame, path: Path, expected: tuple[str, ...]
) -> None:
    missing = [column for column in expected if column not in frame.columns]
    if missing:
        raise ValueError(f"{path.name} missing expected columns: {', '.join(missing)}")


def _base_report(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": len(frame),
        "columns": len(frame.columns),
        "column_names": list(frame.columns),
        "column_types": {name: str(dtype) for name, dtype in frame.dtypes.items()},
        "missing_by_column": {
            name: int(count) for name, count in frame.isna().sum().items()
        },
        "duplicate_rows": int(frame.duplicated().sum()),
    }


def _file_identity(path: Path) -> dict[str, str | int]:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"file_bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def _date_range(values: pd.Series[Any]) -> list[str | None]:
    parsed = pd.to_datetime(values, errors="coerce")
    if not parsed.notna().any():
        return [None, None]
    return [parsed.min().date().isoformat(), parsed.max().date().isoformat()]


def _normalized_zips(values: pd.Series[Any]) -> pd.Series[Any]:
    cleaned = values.astype("string").str.strip()
    return cleaned.str.replace(r"^(\d{5})\.0$", r"\1", regex=True)


def _zip_values(values: pd.Series[Any]) -> set[str]:
    cleaned = _normalized_zips(values).dropna()
    return set(cleaned[cleaned.ne("")])


def inspect_raw_data(raw_dir: Path) -> dict[str, dict[str, Any]]:
    sales_path = raw_dir / "redfin_data.csv"
    series_path = raw_dir / "zipcode_saleprice.csv"
    sales = _read_csv(sales_path, ("ZIP OR POSTAL CODE", "MLS#"))
    series = _read_csv(series_path, ("RegionName",))
    _require_columns(sales, sales_path, REDFIN_COLUMNS)
    _require_columns(series, series_path, ZIP_COLUMNS)

    month_columns = sorted(
        name
        for name in series.columns
        if isinstance(name, str) and MONTH_COLUMN.fullmatch(name)
    )
    if not month_columns:
        raise ValueError(f"{series_path.name} has no monthly date columns")

    sales_report = _base_report(sales)
    sales_report.update(_file_identity(sales_path))
    sold_dates = pd.to_datetime(sales["SOLD DATE"], errors="coerce")
    sale_prices = pd.to_numeric(sales["PRICE"], errors="coerce")
    mls_ids = sales["MLS#"].dropna().str.strip()
    mls_ids = mls_ids[mls_ids.ne("")]
    sales_report.update(
        {
            "target_column": "PRICE",
            "feature_columns": list(REDFIN_FEATURE_COLUMNS),
            "missing_expected_columns": [],
            "sold_date_range": _date_range(sales["SOLD DATE"]),
            "invalid_nonblank_sold_dates": int(
                (sales["SOLD DATE"].notna() & sold_dates.isna()).sum()
            ),
            "invalid_nonblank_prices": int(
                (sales["PRICE"].notna() & sale_prices.isna()).sum()
            ),
            "nonpositive_prices": int(sale_prices.le(0).sum()),
            "duplicate_nonblank_mls_ids": int(mls_ids.duplicated().sum()),
            "rows_with_sale_date_price_and_features": int(
                sales[["SOLD DATE", "PRICE", *REDFIN_FEATURE_COLUMNS]]
                .notna()
                .all(axis=1)
                .sum()
            ),
        }
    )

    series_report = _base_report(series)
    series_report.update(_file_identity(series_path))
    monthly_values = series[month_columns].apply(pd.to_numeric, errors="coerce")
    first_month = pd.Timestamp(month_columns[0])
    last_month = pd.Timestamp(month_columns[-1])
    expected_months = pd.date_range(first_month, last_month, freq="MS")
    home_zips = _zip_values(sales["ZIP OR POSTAL CODE"])
    series_zips = _zip_values(series["RegionName"])
    sale_zip_values = _normalized_zips(sales["ZIP OR POSTAL CODE"])
    series_report.update(
        {
            "series_metric": "unverified",
            "missing_expected_columns": [],
            "monthly_columns": len(month_columns),
            "month_range": [month_columns[0], month_columns[-1]],
            "missing_month_columns": sorted(
                set(expected_months.strftime("%Y-%m-%d")) - set(month_columns)
            ),
            "missing_monthly_values": int(series[month_columns].isna().sum().sum()),
            "invalid_nonblank_monthly_values": int(
                (series[month_columns].notna() & monthly_values.isna()).sum().sum()
            ),
            "duplicate_region_names": int(
                series["RegionName"].dropna().duplicated().sum()
            ),
            "zip_overlap": sorted(home_zips & series_zips),
            "home_zips_without_series": sorted(home_zips - series_zips),
            "sale_rows_with_series_zip": int(sale_zip_values.isin(series_zips).sum()),
        }
    )
    return {sales_path.name: sales_report, series_path.name: series_report}


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect HomeLens raw CSV datasets")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/processed/inventory.json")
    )
    args = parser.parse_args()
    try:
        report = inspect_raw_data(args.raw_dir)
    except (FileNotFoundError, ValueError, pd.errors.ParserError) as exc:
        parser.error(str(exc))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote inventory to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
