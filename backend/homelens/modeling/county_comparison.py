"""Compare the selected county-verified study cohort with the ZIP baseline."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor

from homelens.data.inventory import _file_identity, _read_csv, _require_columns
from homelens.data.prepare import OUTPUT_COLUMNS
from homelens.modeling.baseline import (
    CATEGORICAL_COLUMNS,
    MODEL_CONFIG,
    SMALL_SLICE_MIN_ROWS,
    _features,
    _metrics,
    _read_audit,
    _validate_cohort,
)

FIXED_LOSS = "poisson"


def _fit(
    frame: pd.DataFrame,
) -> tuple[HistGradientBoostingRegressor, dict[str, list[str]]]:
    train = frame.loc[frame["split"].eq("train")]
    categories = {
        column: sorted(train[column].astype("string").unique().tolist())
        for column in CATEGORICAL_COLUMNS
    }
    model = HistGradientBoostingRegressor(**{**MODEL_CONFIG, "loss": FIXED_LOSS})
    model.fit(_features(train, categories), train["price_usd"])
    return model, categories


def _predict(
    model: HistGradientBoostingRegressor,
    categories: dict[str, list[str]],
    frame: pd.DataFrame,
) -> np.ndarray[Any, Any]:
    return np.asarray(model.predict(_features(frame, categories)), dtype=float)


def _aggregate(
    frame: pd.DataFrame,
    predicted: np.ndarray[Any, Any],
    validation_halves: bool = False,
) -> dict[str, Any]:
    scored = frame.copy()
    scored["prediction"] = predicted

    def slice_metrics(group: pd.DataFrame) -> dict[str, Any]:
        if len(group) < SMALL_SLICE_MIN_ROWS:
            return {"rows": len(group), "small_slice": True}
        return _metrics(group["price_usd"], group["prediction"].to_numpy())

    report: dict[str, Any] = {
        "overall": _metrics(frame["price_usd"], predicted),
        "by_zip": {
            str(code): slice_metrics(group)
            for code, group in scored.groupby("zip", sort=True)
        },
        "by_property_type": {
            str(kind): slice_metrics(group)
            for kind, group in scored.groupby("property_type", sort=True)
        },
    }
    if validation_halves:
        dates = pd.to_datetime(scored["sale_date"], format="%Y-%m-%d")
        scored["half"] = np.where(
            dates.lt(pd.Timestamp(2024, 7, 1)), "Jan-Jun", "Jul-Dec"
        )
        report["by_2024_half"] = {
            str(half): slice_metrics(group)
            for half, group in scored.groupby("half", sort=True)
        }
    return report


def _require_selected_subset(original: pd.DataFrame, selected: pd.DataFrame) -> None:
    original_counts = original.value_counts(subset=list(OUTPUT_COLUMNS), dropna=False)
    selected_counts = selected.value_counts(subset=list(OUTPUT_COLUMNS), dropna=False)
    available = original_counts.reindex(selected_counts.index, fill_value=0)
    if not selected_counts.le(available).all():
        raise ValueError("county-verified cohort contains rows outside ZIP cohort")


def compare_county_cohorts(
    original: pd.DataFrame,
    selected: pd.DataFrame,
    validation_start: date,
    test_start: date,
) -> dict[str, Any]:
    original = _validate_cohort(original, validation_start, test_start)
    selected = _validate_cohort(selected, validation_start, test_start)
    _require_selected_subset(original, selected)

    original_model, original_categories = _fit(original)
    selected_model, selected_categories = _fit(selected)
    original_validation = original.loc[original["split"].eq("validation")]
    selected_validation = selected.loc[selected["split"].eq("validation")]
    selected_test = selected.loc[selected["split"].eq("test")]

    return {
        "cohort_scope": "eight selected ZIPs inside Durham County boundary",
        "county_boundary_validated": True,
        "county_wide_supported": False,
        "fixed_loss": FIXED_LOSS,
        "fixed_model_config": {**MODEL_CONFIG, "loss": FIXED_LOSS},
        "scikit_learn_version": sklearn.__version__,
        "split_boundaries": {
            "validation_start": validation_start.isoformat(),
            "test_start": test_start.isoformat(),
        },
        "split_counts": {
            name: {
                split: int(frame["split"].eq(split).sum())
                for split in ("train", "validation", "test")
            }
            for name, frame in (
                ("original_zip", original),
                ("county_verified", selected),
            )
        },
        "validation": {
            "original_model_on_full_zip_scope": _aggregate(
                original_validation,
                _predict(original_model, original_categories, original_validation),
                validation_halves=True,
            ),
            "original_model_on_common_sales": _aggregate(
                selected_validation,
                _predict(original_model, original_categories, selected_validation),
                validation_halves=True,
            ),
            "selected_model_on_common_sales": _aggregate(
                selected_validation,
                _predict(selected_model, selected_categories, selected_validation),
                validation_halves=True,
            ),
        },
        "held_out_test": {
            "selected_model": _aggregate(
                selected_test,
                _predict(selected_model, selected_categories, selected_test),
            ),
            "use": "descriptive evaluation after the 2024 geography decision",
        },
        "selection_note": (
            "County-verified study ZIPs were chosen for geographic validity in the "
            "executed notebook. The 2024 validation period also informed the earlier "
            "loss choice, so this comparison is exploratory; no serving model or "
            "county-wide claim follows from it."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare county-verified valuation cohort"
    )
    parser.add_argument(
        "--original", type=Path, default=Path("data/processed/modeling_cohort.csv")
    )
    parser.add_argument(
        "--original-audit",
        type=Path,
        default=Path("data/processed/modeling_cohort_audit.json"),
    )
    parser.add_argument(
        "--selected",
        type=Path,
        default=Path("data/processed/modeling_cohort_county_verified.csv"),
    )
    parser.add_argument(
        "--selected-audit",
        type=Path,
        default=Path("data/processed/modeling_cohort_county_verified_audit.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/county_cohort_comparison.json"),
    )
    args = parser.parse_args()
    try:
        validation_start, test_start, original_audit = _read_audit(args.original_audit)
        selected_validation_start, selected_test_start, selected_audit = _read_audit(
            args.selected_audit
        )
        if (validation_start, test_start) != (
            selected_validation_start,
            selected_test_start,
        ):
            raise ValueError("cohort audits have different temporal boundaries")
        if (
            original_audit.get("source_identity")
            != selected_audit.get("source_identity")
            or selected_audit.get("rules", {}).get("county_boundary_validated")
            is not True
            or "boundary_source_identity" not in selected_audit
        ):
            raise ValueError("cohort audits do not describe the same verified source")
        original = _read_csv(
            args.original, ("sale_date", "property_type", "zip", "split")
        )
        selected = _read_csv(
            args.selected, ("sale_date", "property_type", "zip", "split")
        )
        _require_columns(original, args.original, OUTPUT_COLUMNS)
        _require_columns(selected, args.selected, OUTPUT_COLUMNS)
        report = compare_county_cohorts(
            original, selected, validation_start, test_start
        )
        if any(
            audit.get("prepared_rows") != len(frame)
            or audit.get("split_counts") != report["split_counts"][name]
            for name, frame, audit in (
                ("original_zip", original, original_audit),
                ("county_verified", selected, selected_audit),
            )
        ):
            raise ValueError("cohort rows do not match preparation audits")
    except (
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
        pd.errors.ParserError,
    ) as exc:
        parser.error(str(exc))

    report["original_cohort_identity"] = _file_identity(args.original)
    report["selected_cohort_identity"] = _file_identity(args.selected)
    report["original_audit_identity"] = _file_identity(args.original_audit)
    report["selected_audit_identity"] = _file_identity(args.selected_audit)
    report["boundary_source_identity"] = selected_audit["boundary_source_identity"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote county cohort comparison to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
