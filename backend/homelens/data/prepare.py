"""Prepare a narrow, auditable residential-sales cohort for baseline modeling."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .inventory import (
    REDFIN_COLUMNS,
    _file_identity,
    _normalized_zips,
    _read_csv,
    _require_columns,
)

RESIDENTIAL_TYPES = (
    "Single Family Residential",
    "Townhouse",
    "Condo/Co-op",
)
STUDY_ZIPS = (
    "27503",
    "27701",
    "27703",
    "27704",
    "27705",
    "27707",
    "27712",
    "27713",
)
NUMERIC_FEATURES = ("BEDS", "BATHS", "SQUARE FEET", "YEAR BUILT")
PREDICTOR_COLUMNS = (
    "beds",
    "baths",
    "square_feet",
    "year_built",
    "property_type",
    "zip",
)
OUTPUT_COLUMNS = ("sale_date", "price_usd", *PREDICTOR_COLUMNS, "split")
DEFAULT_VALIDATION_START = date(2024, 1, 1)
DEFAULT_TEST_START = date(2025, 1, 1)


def _keep(
    frame: pd.DataFrame,
    mask: pd.Series[Any],
    rejected: dict[str, int],
    reason: str,
) -> pd.DataFrame:
    kept = frame.loc[mask.fillna(False)].copy()
    rejected[reason] = len(frame) - len(kept)
    return kept


def _date_range(frame: pd.DataFrame) -> list[str | None]:
    if frame.empty:
        return [None, None]
    return [str(frame["sale_date"].min()), str(frame["sale_date"].max())]


def prepare_sales(
    raw_dir: Path,
    validation_start: date = DEFAULT_VALIDATION_START,
    test_start: date = DEFAULT_TEST_START,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if validation_start >= test_start:
        raise ValueError("validation start must be before test start")

    path = raw_dir / "redfin_data.csv"
    source = _read_csv(path, ("ZIP OR POSTAL CODE", "MLS#"))
    _require_columns(source, path, (*REDFIN_COLUMNS, "SALE TYPE", "STATE OR PROVINCE"))
    rejected: dict[str, int] = {}
    frame = source.drop_duplicates().copy()
    rejected["exact_duplicates"] = len(source) - len(frame)

    frame = _keep(
        frame,
        frame["SALE TYPE"].astype("string").str.strip().eq("PAST SALE"),
        rejected,
        "not_past_sale",
    )
    sold_dates = pd.to_datetime(frame["SOLD DATE"], format="mixed", errors="coerce")
    frame = _keep(frame, sold_dates.notna(), rejected, "missing_or_invalid_sale_date")
    frame["sale_date"] = sold_dates.loc[frame.index].dt.strftime("%Y-%m-%d")

    prices = pd.to_numeric(frame["PRICE"], errors="coerce")
    frame = _keep(
        frame,
        prices.gt(0) & prices.lt(float("inf")),
        rejected,
        "missing_invalid_or_nonpositive_price",
    )
    frame["price_usd"] = prices.loc[frame.index]
    frame = _keep(
        frame,
        frame["PROPERTY TYPE"].isin(RESIDENTIAL_TYPES),
        rejected,
        "outside_initial_residential_types",
    )
    frame = _keep(
        frame,
        frame["STATE OR PROVINCE"].astype("string").str.strip().eq("NC"),
        rejected,
        "outside_north_carolina",
    )

    for column in NUMERIC_FEATURES:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["zip"] = _normalized_zips(frame["ZIP OR POSTAL CODE"])
    complete = frame[list(NUMERIC_FEATURES)].notna().all(axis=1) & frame["zip"].notna()
    frame = _keep(frame, complete, rejected, "missing_core_features")
    frame = _keep(
        frame,
        frame["zip"].str.fullmatch(r"\d{5}"),
        rejected,
        "invalid_zip_format",
    )
    frame = _keep(
        frame,
        frame["zip"].isin(STUDY_ZIPS),
        rejected,
        "outside_study_zips",
    )

    sale_year = pd.to_datetime(frame["sale_date"]).dt.year
    plausible = (
        frame["BEDS"].ge(0)
        & frame["BEDS"].lt(float("inf"))
        & frame["BATHS"].gt(0)
        & frame["BATHS"].lt(float("inf"))
        & frame["SQUARE FEET"].ge(300)
        & frame["SQUARE FEET"].lt(float("inf"))
        & frame["YEAR BUILT"].ge(1800)
        & frame["YEAR BUILT"].le(sale_year)
        & frame["YEAR BUILT"].mod(1).eq(0)
    )
    frame = _keep(frame, plausible, rejected, "implausible_core_features")

    prepared = frame.rename(
        columns={
            "BEDS": "beds",
            "BATHS": "baths",
            "SQUARE FEET": "square_feet",
            "YEAR BUILT": "year_built",
            "PROPERTY TYPE": "property_type",
        }
    ).copy()
    prepared["year_built"] = prepared["year_built"].astype(int)
    sale_dates = pd.to_datetime(prepared["sale_date"])
    prepared["split"] = "train"
    prepared.loc[sale_dates >= pd.Timestamp(validation_start), "split"] = "validation"
    prepared.loc[sale_dates >= pd.Timestamp(test_start), "split"] = "test"
    prepared = prepared[list(OUTPUT_COLUMNS)].sort_values(
        ["sale_date", "zip", "price_usd"], kind="stable"
    )
    prepared = prepared.reset_index(drop=True)

    split_counts = {
        split: int(prepared["split"].eq(split).sum())
        for split in ("train", "validation", "test")
    }
    report: dict[str, Any] = {
        "source_file": path.name,
        "source_identity": _file_identity(path),
        "source_rows": len(source),
        "rejected_rows_by_stage": rejected,
        "prepared_rows": len(prepared),
        "split_boundaries": {
            "validation_start": validation_start.isoformat(),
            "test_start": test_start.isoformat(),
        },
        "split_counts": split_counts,
        "split_date_ranges": {
            split: _date_range(prepared.loc[prepared["split"].eq(split)])
            for split in split_counts
        },
        "target_column": "price_usd",
        "predictor_columns": list(PREDICTOR_COLUMNS),
        "metadata_columns": ["sale_date", "split"],
        "rules": {
            "property_types": list(RESIDENTIAL_TYPES),
            "study_zips": list(STUDY_ZIPS),
            "geography_scope": "selected ZIPs, not a county-boundary check",
            "minimum_square_feet": 300,
            "minimum_year_built": 1800,
            "year_built_must_not_exceed_sale_year": True,
            "positive_price_required": True,
            "high_price_cap": None,
            "zip_history_values_joined": False,
            "county_boundary_validated": False,
            "exact_duplicates_only": True,
            "target_derived_field_excluded": "$/SQUARE FEET",
        },
    }
    return prepared, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare HomeLens residential sales")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/processed/modeling_cohort.csv")
    )
    parser.add_argument(
        "--audit", type=Path, default=Path("data/processed/modeling_cohort_audit.json")
    )
    parser.add_argument(
        "--validation-start", type=date.fromisoformat, default=DEFAULT_VALIDATION_START
    )
    parser.add_argument(
        "--test-start", type=date.fromisoformat, default=DEFAULT_TEST_START
    )
    args = parser.parse_args()
    try:
        prepared, report = prepare_sales(
            args.raw_dir, args.validation_start, args.test_start
        )
    except (FileNotFoundError, ValueError, pd.errors.ParserError) as exc:
        parser.error(str(exc))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    prepared.to_csv(args.output, index=False)
    args.audit.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(prepared)} rows to {args.output} and audit to {args.audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
