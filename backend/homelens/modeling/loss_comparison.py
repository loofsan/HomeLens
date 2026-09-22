"""Compare a validation-selected high-price loss with the fixed baseline."""

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
from sklearn.metrics import mean_absolute_error

from homelens.data.inventory import _file_identity, _read_csv, _require_columns
from homelens.data.prepare import OUTPUT_COLUMNS, PREDICTOR_COLUMNS
from homelens.modeling.baseline import (
    CATEGORICAL_COLUMNS,
    MODEL_CONFIG,
    SMALL_SLICE_MIN_ROWS,
    _evaluation,
    _features,
    _read_audit,
    _validate_cohort,
)

REFERENCE_LOSS = "absolute_error"
CANDIDATE_LOSS = "poisson"
MIN_HIGH_PRICE_IMPROVEMENT = 0.10
MAX_OVERALL_MAE_INCREASE = 0.05
INTERVAL_COVERAGE = 0.90


def _choose_loss(
    actual: np.ndarray[Any, Any],
    reference: np.ndarray[Any, Any],
    candidate: np.ndarray[Any, Any],
    high_price: np.ndarray[Any, Any],
) -> dict[str, Any]:
    reference_mae = float(mean_absolute_error(actual, reference))
    candidate_mae = float(mean_absolute_error(actual, candidate))
    high_rows = int(high_price.sum())
    supported = high_rows >= SMALL_SLICE_MIN_ROWS
    reference_high_mae = (
        float(mean_absolute_error(actual[high_price], reference[high_price]))
        if supported
        else None
    )
    candidate_high_mae = (
        float(mean_absolute_error(actual[high_price], candidate[high_price]))
        if supported
        else None
    )
    qualifies = (
        supported
        and reference_high_mae is not None
        and candidate_high_mae is not None
        and reference_high_mae > 0
        and candidate_high_mae <= reference_high_mae * (1 - MIN_HIGH_PRICE_IMPROVEMENT)
        and candidate_mae <= reference_mae * (1 + MAX_OVERALL_MAE_INCREASE)
    )
    return {
        "selected_loss": CANDIDATE_LOSS if qualifies else REFERENCE_LOSS,
        "high_price_rows": high_rows,
        "minimum_high_price_mae_improvement": MIN_HIGH_PRICE_IMPROVEMENT,
        "maximum_overall_mae_increase": MAX_OVERALL_MAE_INCREASE,
        "reference_overall_mae_usd": round(reference_mae, 2),
        "candidate_overall_mae_usd": round(candidate_mae, 2),
        "reference_high_price_mae_usd": (
            round(reference_high_mae, 2) if reference_high_mae is not None else None
        ),
        "candidate_high_price_mae_usd": (
            round(candidate_high_mae, 2) if candidate_high_mae is not None else None
        ),
    }


def _interval_check(
    validation: pd.DataFrame,
    predicted: np.ndarray[Any, Any],
    high_price_threshold: float,
    midpoint: date,
) -> dict[str, Any]:
    actual = validation["price_usd"].to_numpy(dtype=float)
    dates = pd.to_datetime(validation["sale_date"], format="%Y-%m-%d")
    calibration = dates.lt(pd.Timestamp(midpoint)).to_numpy()
    assessment = ~calibration
    if (
        calibration.sum() < SMALL_SLICE_MIN_ROWS
        or assessment.sum() < SMALL_SLICE_MIN_ROWS
    ):
        raise ValueError("interval check requires supported temporal halves")
    calibration_errors = np.abs(actual[calibration] - predicted[calibration])
    level = min(
        1.0,
        float(np.ceil((len(calibration_errors) + 1) * INTERVAL_COVERAGE))
        / len(calibration_errors),
    )
    half_width = float(np.quantile(calibration_errors, level, method="higher"))
    covered = np.abs(actual - predicted) <= half_width
    high_assessment = assessment & (actual > high_price_threshold)
    high_rows = int(high_assessment.sum())
    return {
        "calibration_rows": int(calibration.sum()),
        "assessment_rows": int(assessment.sum()),
        "high_price_assessment_rows": high_rows,
        "calibration_end_exclusive": midpoint.isoformat(),
        "nominal_coverage": INTERVAL_COVERAGE,
        "half_width_usd": round(half_width, 2),
        "assessment_coverage": round(float(covered[assessment].mean()), 4),
        "high_price_coverage": (
            round(float(covered[high_assessment].mean()), 4)
            if high_rows >= SMALL_SLICE_MIN_ROWS
            else None
        ),
        "high_price_small_slice": high_rows < SMALL_SLICE_MIN_ROWS,
    }


def compare_losses(
    cohort: pd.DataFrame, validation_start: date, test_start: date
) -> dict[str, Any]:
    frame = _validate_cohort(cohort, validation_start, test_start)
    splits = {
        name: frame.loc[frame["split"].eq(name)].copy()
        for name in ("train", "validation", "test")
    }
    train = splits["train"]
    validation = splits["validation"]
    test = splits["test"]
    high_price_threshold = float(train["price_usd"].quantile(0.9))
    training_price_quantiles = (
        float(train["price_usd"].quantile(0.5)),
        high_price_threshold,
    )
    categories = {
        column: sorted(train[column].astype("string").unique().tolist())
        for column in CATEGORICAL_COLUMNS
    }
    train_features = _features(train, categories)
    validation_features = _features(validation, categories)
    models = {}
    validation_predictions = {}
    for loss in (REFERENCE_LOSS, CANDIDATE_LOSS):
        model = HistGradientBoostingRegressor(**{**MODEL_CONFIG, "loss": loss})
        model.fit(train_features, train["price_usd"])
        models[loss] = model
        validation_predictions[loss] = model.predict(validation_features)

    validation_actual = validation["price_usd"].to_numpy(dtype=float)
    high_price = validation_actual > high_price_threshold
    decision = _choose_loss(
        validation_actual,
        validation_predictions[REFERENCE_LOSS],
        validation_predictions[CANDIDATE_LOSS],
        high_price,
    )
    selected_loss = str(decision["selected_loss"])
    midpoint = (pd.Timestamp(validation_start) + pd.DateOffset(months=6)).date()
    interval_checks = {
        loss: _interval_check(
            validation, validation_predictions[loss], high_price_threshold, midpoint
        )
        for loss in dict.fromkeys((REFERENCE_LOSS, selected_loss))
    }
    test_features = _features(test, categories)
    final_test = {
        loss: _evaluation(
            test,
            models[loss].predict(test_features),
            training_price_quantiles,
        )
        for loss in dict.fromkeys((REFERENCE_LOSS, selected_loss))
    }
    return {
        "cohort_scope": "three residential property types in eight selected ZIPs",
        "county_boundary_validated": False,
        "predictor_columns": list(PREDICTOR_COLUMNS),
        "training_only_categories": categories,
        "split_counts": {name: len(rows) for name, rows in splits.items()},
        "split_boundaries": {
            "validation_start": validation_start.isoformat(),
            "test_start": test_start.isoformat(),
        },
        "training_p90_usd": round(high_price_threshold, 2),
        "fixed_model_config": MODEL_CONFIG,
        "scikit_learn_version": sklearn.__version__,
        "validation_decision": decision,
        "validation_evaluations": {
            loss: _evaluation(validation, predicted, training_price_quantiles)
            for loss, predicted in validation_predictions.items()
        },
        "validation_interval_checks": interval_checks,
        "interval_note": (
            "Exploratory only: 2024 validation also selected the model, so "
            "coverage is not an independent guarantee or a serving interval"
        ),
        "final_test_evaluations": final_test,
        "test_use": "descriptive comparison after validation-only selection",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare validation-selected valuation loss with baseline"
    )
    parser.add_argument(
        "--cohort", type=Path, default=Path("data/processed/modeling_cohort.csv")
    )
    parser.add_argument(
        "--cohort-audit",
        type=Path,
        default=Path("data/processed/modeling_cohort_audit.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/processed/loss_comparison.json")
    )
    args = parser.parse_args()
    try:
        validation_start, test_start, audit = _read_audit(args.cohort_audit)
        cohort = _read_csv(args.cohort, ("sale_date", "property_type", "zip", "split"))
        _require_columns(cohort, args.cohort, OUTPUT_COLUMNS)
        report = compare_losses(cohort, validation_start, test_start)
        if (
            audit.get("prepared_rows") != len(cohort)
            or audit.get("split_counts") != report["split_counts"]
        ):
            raise ValueError("cohort rows do not match the preparation audit")
    except (
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
        pd.errors.ParserError,
    ) as exc:
        parser.error(str(exc))

    report["cohort_identity"] = _file_identity(args.cohort)
    report["cohort_audit_identity"] = _file_identity(args.cohort_audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote loss comparison report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
