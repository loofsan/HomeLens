"""Assess a fixed, research-only valuation interval on held-out sales."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn

from homelens.data.inventory import _file_identity, _read_csv, _require_columns
from homelens.data.prepare import OUTPUT_COLUMNS
from homelens.modeling.baseline import (
    MODEL_CONFIG,
    SMALL_SLICE_MIN_ROWS,
    _read_audit,
    _validate_cohort,
)
from homelens.modeling.county_comparison import FIXED_LOSS, _fit, _predict

CALIBRATION_END = date(2024, 7, 1)
UPPER_TAIL = 0.01
LOWER_TAIL = 0.09
NOMINAL_COVERAGE = 0.90


def _conformal_quantile(scores: np.ndarray[Any, Any], coverage: float) -> float:
    values = np.asarray(scores, dtype=float)
    if len(values) == 0 or not np.isfinite(values).all():
        raise ValueError("calibration scores must be nonempty and finite")
    if not 0 < coverage < 1:
        raise ValueError("coverage must be between zero and one")
    rank = min(len(values), int(np.ceil((len(values) + 1) * coverage)))
    return float(np.sort(values)[rank - 1])


def _calibrate(
    actual: np.ndarray[Any, Any], predicted: np.ndarray[Any, Any]
) -> dict[str, float]:
    if len(actual) != len(predicted) or len(actual) < SMALL_SLICE_MIN_ROWS:
        raise ValueError("interval calibration requires at least 30 paired sales")
    if not np.isfinite(predicted).all() or np.any(predicted <= 0):
        raise ValueError("predictions must be positive and finite")
    residual = actual - predicted
    return {
        "lower_scale": _conformal_quantile(
            np.maximum(-residual, 0) / predicted, 1 - LOWER_TAIL
        ),
        "upper_scale": _conformal_quantile(
            np.maximum(residual, 0) / predicted, 1 - UPPER_TAIL
        ),
        "global_absolute_half_width_usd": _conformal_quantile(
            np.abs(residual), NOMINAL_COVERAGE
        ),
    }


def _bounds(
    predicted: np.ndarray[Any, Any], calibration: dict[str, float]
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    return (
        np.maximum(0, predicted * (1 - calibration["lower_scale"])),
        predicted * (1 + calibration["upper_scale"]),
    )


def _slice_metrics(group: pd.DataFrame) -> dict[str, Any]:
    rows = len(group)
    if rows < SMALL_SLICE_MIN_ROWS:
        return {"rows": rows, "small_slice": True}
    return {
        "rows": rows,
        "small_slice": False,
        "coverage": round(float(group["covered"].mean()), 4),
        "below_lower_rate": round(float(group["below_lower"].mean()), 4),
        "above_upper_rate": round(float(group["above_upper"].mean()), 4),
        "median_width_usd": round(float(group["width_usd"].median()), 2),
        "median_width_to_prediction": round(
            float(group["width_usd"].median() / group["prediction"].median()), 3
        ),
    }


def _assess(
    frame: pd.DataFrame,
    predicted: np.ndarray[Any, Any],
    lower: np.ndarray[Any, Any],
    upper: np.ndarray[Any, Any],
    train_p50: float,
    train_p90: float,
) -> dict[str, Any]:
    if not len(frame) == len(predicted) == len(lower) == len(upper):
        raise ValueError("interval assessment arrays must have equal lengths")
    scored = frame[["price_usd", "property_type", "zip"]].copy()
    actual = scored["price_usd"].to_numpy(dtype=float)
    scored["prediction"] = predicted
    scored["covered"] = (actual >= lower) & (actual <= upper)
    scored["below_lower"] = actual < lower
    scored["above_upper"] = actual > upper
    scored["width_usd"] = upper - lower
    scored["training_price_band"] = np.where(
        actual <= train_p50,
        "at_or_below_train_p50",
        np.where(actual <= train_p90, "train_p50_to_p90", "above_train_p90"),
    )
    return {
        "overall": _slice_metrics(scored),
        "by_training_price_band": {
            str(name): _slice_metrics(group)
            for name, group in scored.groupby("training_price_band", sort=True)
        },
        "by_property_type": {
            str(name): _slice_metrics(group)
            for name, group in scored.groupby("property_type", sort=True)
        },
        "by_zip": {
            str(name): _slice_metrics(group)
            for name, group in scored.groupby("zip", sort=True)
        },
    }


def assess_fixed_interval(
    cohort: pd.DataFrame, validation_start: date, test_start: date
) -> dict[str, Any]:
    if (validation_start, test_start) != (date(2024, 1, 1), date(2025, 1, 1)):
        raise ValueError(
            "fixed interval assessment requires the accepted temporal split"
        )
    frame = _validate_cohort(cohort, validation_start, test_start)
    train = frame.loc[frame["split"].eq("train")]
    validation = frame.loc[frame["split"].eq("validation")]
    test = frame.loc[frame["split"].eq("test")]
    model, categories = _fit(frame)
    validation_predicted = _predict(model, categories, validation)
    dates = pd.to_datetime(validation["sale_date"], format="%Y-%m-%d")
    first_half = dates.lt(pd.Timestamp(CALIBRATION_END)).to_numpy()
    second_half = ~first_half
    if (
        first_half.sum() < SMALL_SLICE_MIN_ROWS
        or second_half.sum() < SMALL_SLICE_MIN_ROWS
        or len(test) < SMALL_SLICE_MIN_ROWS
    ):
        raise ValueError("temporal calibration, assessment, and test need 30 sales")
    validation_actual = validation["price_usd"].to_numpy(dtype=float)
    first_calibration = _calibrate(
        validation_actual[first_half], validation_predicted[first_half]
    )
    second_prediction = validation_predicted[second_half]
    second_lower, second_upper = _bounds(second_prediction, first_calibration)
    train_p50 = float(train["price_usd"].quantile(0.5))
    train_p90 = float(train["price_usd"].quantile(0.9))
    validation_assessment = _assess(
        validation.loc[second_half],
        second_prediction,
        second_lower,
        second_upper,
        train_p50,
        train_p90,
    )

    # Method and tails were frozen using 2024 before the single 2025 assessment.
    final_calibration = _calibrate(validation_actual, validation_predicted)
    test_predicted = _predict(model, categories, test)
    test_lower, test_upper = _bounds(test_predicted, final_calibration)
    held_out_test = _assess(
        test, test_predicted, test_lower, test_upper, train_p50, train_p90
    )
    return {
        "cohort_scope": "eight selected ZIPs inside Durham County boundary",
        "county_wide_supported": False,
        "fixed_point_model": {"config": {**MODEL_CONFIG, "loss": FIXED_LOSS}},
        "scikit_learn_version": sklearn.__version__,
        "train_price_p50_usd": round(train_p50, 2),
        "train_price_p90_usd": round(train_p90, 2),
        "method": {
            "name": "asymmetric_relative_conformal",
            "nominal_coverage": NOMINAL_COVERAGE,
            "lower_tail": LOWER_TAIL,
            "upper_tail": UPPER_TAIL,
            "selection": "fixed after July-December 2024 exploratory assessment",
        },
        "validation_assessment": {
            "calibration_period": "January-June 2024",
            "calibration_rows": int(first_half.sum()),
            "assessment_period": "July-December 2024",
            "calibration_scales": first_calibration,
            "metrics": validation_assessment,
        },
        "held_out_test": {
            "calibration_period": "all of 2024, fixed method",
            "calibration_rows": len(validation),
            "assessment_period": "January-May 2025",
            "calibration_scales": final_calibration,
            "metrics": held_out_test,
        },
        "serving_interval_approved": False,
        "serving_note": (
            "Research only: 2024 also informed the point-model loss choice. "
            "Coverage varies by price band and ZIP, and widths are large. "
            "No interval is exported or exposed by the API."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assess research-only valuation interval"
    )
    parser.add_argument(
        "--cohort",
        type=Path,
        default=Path("data/processed/modeling_cohort_county_verified.csv"),
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path("data/processed/modeling_cohort_county_verified_audit.json"),
    )
    parser.add_argument(
        "--comparison",
        type=Path,
        default=Path("data/processed/county_cohort_comparison.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/uncertainty_report.json"),
    )
    args = parser.parse_args()
    try:
        validation_start, test_start, audit = _read_audit(args.audit)
        cohort = _read_csv(args.cohort, ("sale_date", "property_type", "zip", "split"))
        _require_columns(cohort, args.cohort, OUTPUT_COLUMNS)
        comparison = json.loads(args.comparison.read_text(encoding="utf-8"))
        if (
            audit.get("rules", {}).get("county_boundary_validated") is not True
            or audit.get("prepared_rows") != len(cohort)
            or audit.get("split_counts") != cohort["split"].value_counts().to_dict()
            or comparison.get("selected_cohort_identity") != _file_identity(args.cohort)
            or comparison.get("selected_audit_identity") != _file_identity(args.audit)
            or comparison.get("boundary_source_identity")
            != audit.get("boundary_source_identity")
            or comparison.get("fixed_model_config")
            != {**MODEL_CONFIG, "loss": FIXED_LOSS}
            or comparison.get("scikit_learn_version") != sklearn.__version__
        ):
            raise ValueError("cohort, audit, or accepted comparison is inconsistent")
        report = assess_fixed_interval(cohort, validation_start, test_start)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        pd.errors.ParserError,
    ) as exc:
        parser.error(str(exc))
    report["cohort_identity"] = _file_identity(args.cohort)
    report["audit_identity"] = _file_identity(args.audit)
    report["comparison_identity"] = _file_identity(args.comparison)
    report["boundary_source_identity"] = audit["boundary_source_identity"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote research-only uncertainty report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
