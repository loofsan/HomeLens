"""Evaluate fixed valuation baselines on the prepared temporal splits."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import (
    mean_absolute_error,
    median_absolute_error,
    root_mean_squared_error,
)

from homelens.data.inventory import _file_identity, _read_csv, _require_columns
from homelens.data.prepare import (
    OUTPUT_COLUMNS,
    PREDICTOR_COLUMNS,
    RESIDENTIAL_TYPES,
    STUDY_ZIPS,
)

CATEGORICAL_COLUMNS = ("property_type", "zip")
NUMERIC_COLUMNS = ("beds", "baths", "square_feet", "year_built")
SMALL_SLICE_MIN_ROWS = 30
MODEL_CONFIG: dict[str, Any] = {
    "loss": "absolute_error",
    "max_iter": 100,
    "learning_rate": 0.1,
    "max_leaf_nodes": 15,
    "min_samples_leaf": 20,
    "l2_regularization": 1.0,
    "categorical_features": "from_dtype",
    "early_stopping": False,
    "random_state": 42,
}


def _validate_cohort(
    cohort: pd.DataFrame, validation_start: date, test_start: date
) -> pd.DataFrame:
    if validation_start >= test_start:
        raise ValueError("validation start must be before test start")
    missing = sorted(set(OUTPUT_COLUMNS) - set(cohort.columns))
    if missing:
        raise ValueError(f"cohort missing expected columns: {', '.join(missing)}")

    frame = cohort.copy()
    dates = pd.to_datetime(frame["sale_date"], format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ValueError("cohort contains invalid sale dates")
    expected = pd.Series("train", index=frame.index)
    expected.loc[dates >= pd.Timestamp(validation_start)] = "validation"
    expected.loc[dates >= pd.Timestamp(test_start)] = "test"
    if not frame["split"].eq(expected).all():
        raise ValueError("cohort split labels disagree with temporal boundaries")
    if any(
        not frame["split"].eq(name).any() for name in ("train", "validation", "test")
    ):
        raise ValueError("cohort must contain train, validation, and test rows")

    for column in ("price_usd", *NUMERIC_COLUMNS):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(frame[column].to_numpy(dtype=float)).all():
            raise ValueError(f"cohort contains missing or nonfinite {column}")
    if not frame["price_usd"].gt(0).all():
        raise ValueError("cohort target prices must be positive")
    if not frame["property_type"].isin(RESIDENTIAL_TYPES).all():
        raise ValueError("cohort contains unsupported property types")
    if not frame["zip"].astype("string").isin(STUDY_ZIPS).all():
        raise ValueError("cohort contains ZIPs outside the initial study area")
    return frame


def _features(frame: pd.DataFrame, categories: dict[str, list[str]]) -> pd.DataFrame:
    features = frame[list(PREDICTOR_COLUMNS)].copy()
    for column in CATEGORICAL_COLUMNS:
        values = features[column].astype("string")
        values = values.where(values.isin(categories[column]), None)
        features[column] = pd.Categorical(values, categories=categories[column])
    return features


def _metrics(actual: pd.Series[Any], predicted: np.ndarray[Any, Any]) -> dict[str, Any]:
    absolute_errors = np.abs(actual.to_numpy(dtype=float) - predicted)
    return {
        "rows": len(actual),
        "small_slice": len(actual) < SMALL_SLICE_MIN_ROWS,
        "mae_usd": round(float(mean_absolute_error(actual, predicted)), 2),
        "rmse_usd": round(float(root_mean_squared_error(actual, predicted)), 2),
        "median_absolute_error_usd": round(
            float(median_absolute_error(actual, predicted)), 2
        ),
        "p90_absolute_error_usd": round(float(np.quantile(absolute_errors, 0.9)), 2),
    }


def _evaluation(frame: pd.DataFrame, predicted: np.ndarray[Any, Any]) -> dict[str, Any]:
    scored = frame.copy()
    scored["prediction"] = predicted
    by_column: dict[str, dict[str, Any]] = {}
    for column in ("zip", "property_type"):
        by_column[column] = {
            str(value): _metrics(group["price_usd"], group["prediction"].to_numpy())
            for value, group in scored.groupby(column, sort=True)
        }
    return {
        "overall": _metrics(scored["price_usd"], predicted),
        "by_zip": by_column["zip"],
        "by_property_type": by_column["property_type"],
    }


def evaluate_baselines(
    cohort: pd.DataFrame, validation_start: date, test_start: date
) -> dict[str, Any]:
    frame = _validate_cohort(cohort, validation_start, test_start)
    splits = {
        name: frame.loc[frame["split"].eq(name)].copy()
        for name in ("train", "validation", "test")
    }
    categories = {
        column: sorted(splits["train"][column].astype("string").unique().tolist())
        for column in CATEGORICAL_COLUMNS
    }
    train_features = _features(splits["train"], categories)
    train_target = splits["train"]["price_usd"]
    median_model = DummyRegressor(strategy="median")
    median_model.fit(np.zeros((len(train_features), 1)), train_target)
    gradient_model = HistGradientBoostingRegressor(**MODEL_CONFIG)
    gradient_model.fit(train_features, train_target)

    evaluations: dict[str, dict[str, Any]] = {
        "training_median": {},
        "hist_gradient_boosting": {},
    }
    for split in ("validation", "test"):
        subset = splits[split]
        evaluations["training_median"][split] = _evaluation(
            subset, median_model.predict(np.zeros((len(subset), 1)))
        )
        evaluations["hist_gradient_boosting"][split] = _evaluation(
            subset, gradient_model.predict(_features(subset, categories))
        )

    return {
        "cohort_scope": "three residential property types in eight selected ZIPs",
        "county_boundary_validated": False,
        "predictor_columns": list(PREDICTOR_COLUMNS),
        "training_only_categories": categories,
        "split_boundaries": {
            "validation_start": validation_start.isoformat(),
            "test_start": test_start.isoformat(),
        },
        "split_counts": {name: len(rows) for name, rows in splits.items()},
        "split_date_ranges": {
            name: [str(rows["sale_date"].min()), str(rows["sale_date"].max())]
            for name, rows in splits.items()
        },
        "training_median_usd": round(float(train_target.median()), 2),
        "model_config": MODEL_CONFIG,
        "small_slice_min_rows": SMALL_SLICE_MIN_ROWS,
        "scikit_learn_version": sklearn.__version__,
        "evaluations": evaluations,
    }


def _read_audit(path: Path) -> tuple[date, date, dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing cohort audit: {path}")
    audit = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(audit, dict):
        raise ValueError("cohort audit must be a JSON object")
    try:
        boundaries = audit["split_boundaries"]
        validation_start = date.fromisoformat(boundaries["validation_start"])
        test_start = date.fromisoformat(boundaries["test_start"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("cohort audit has invalid split boundaries") from exc
    return validation_start, test_start, audit


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate HomeLens valuation baselines"
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
        "--output", type=Path, default=Path("data/processed/baseline_report.json")
    )
    args = parser.parse_args()
    try:
        validation_start, test_start, audit = _read_audit(args.cohort_audit)
        cohort = _read_csv(args.cohort, ("sale_date", "property_type", "zip", "split"))
        _require_columns(cohort, args.cohort, OUTPUT_COLUMNS)
        report = evaluate_baselines(cohort, validation_start, test_start)
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
    print(f"Wrote valuation baseline report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
