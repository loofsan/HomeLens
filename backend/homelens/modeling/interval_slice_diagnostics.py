"""Compare research-only interval slices using 2024 outcomes, never 2025."""

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
from homelens.data.prepare import OUTPUT_COLUMNS, RESIDENTIAL_TYPES, STUDY_ZIPS
from homelens.modeling.baseline import MODEL_CONFIG, SMALL_SLICE_MIN_ROWS, _read_audit
from homelens.modeling.county_comparison import FIXED_LOSS, _fit, _predict
from homelens.modeling.uncertainty import (
    CALIBRATION_END,
    UPPER_TAIL,
    _assess,
    _calibrate,
    _slice_metrics,
)

PREDICTED_BAND_MIN_ROWS = 100
ZIP_MIN_ROWS = 100
EXPLORATORY_ZIP_MIN_ROWS = 60


def _upper_rank_from_max(rows: int) -> int:
    if rows <= 0:
        raise ValueError("calibration group must be nonempty")
    rank = min(rows, int(np.ceil((rows + 1) * (1 - UPPER_TAIL))))
    return rows - rank


def _candidate_bounds(
    actual: np.ndarray[Any, Any],
    predicted: np.ndarray[Any, Any],
    calibration: np.ndarray[Any, Any],
    groups: np.ndarray[Any, Any] | None,
    min_rows: int,
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], dict[str, Any]]:
    global_scales = _calibrate(actual[calibration], predicted[calibration])
    lower_scales = np.full(len(predicted), global_scales["lower_scale"])
    upper_scales = np.full(len(predicted), global_scales["upper_scale"])
    support: dict[str, dict[str, Any]]
    if groups is None:
        rows = int(calibration.sum())
        support = {
            "all": {
                "calibration_rows": rows,
                "assessment_rows": len(predicted) - rows,
                "local_calibration": True,
                "upper_99pct_rank_from_max": _upper_rank_from_max(rows),
            }
        }
    else:
        if len(groups) != len(predicted) or min_rows < SMALL_SLICE_MIN_ROWS:
            raise ValueError("candidate groups or support threshold are invalid")
        support = {}
        for group in np.unique(groups):
            members = groups == group
            local_calibration = calibration & members
            rows = int(local_calibration.sum())
            use_local = rows >= min_rows
            support[str(group)] = {
                "calibration_rows": rows,
                "assessment_rows": int((~calibration & members).sum()),
                "local_calibration": use_local,
                "upper_99pct_rank_from_max": (
                    _upper_rank_from_max(rows) if rows else None
                ),
            }
            if use_local:
                scales = _calibrate(
                    actual[local_calibration], predicted[local_calibration]
                )
                lower_scales[members] = scales["lower_scale"]
                upper_scales[members] = scales["upper_scale"]
    lower = np.maximum(0, predicted * (1 - lower_scales))
    upper = predicted * (1 + upper_scales)
    return lower, upper, support


def _predicted_band_metrics(
    actual: np.ndarray[Any, Any],
    predicted: np.ndarray[Any, Any],
    lower: np.ndarray[Any, Any],
    upper: np.ndarray[Any, Any],
    bands: np.ndarray[Any, Any],
) -> dict[str, Any]:
    scored = pd.DataFrame(
        {
            "band": bands,
            "prediction": predicted,
            "covered": (actual >= lower) & (actual <= upper),
            "below_lower": actual < lower,
            "above_upper": actual > upper,
            "width_usd": upper - lower,
        }
    )
    return {
        str(band): _slice_metrics(group)
        for band, group in scored.groupby("band", sort=True)
    }


def diagnose_2024_candidates(
    cohort: pd.DataFrame, validation_start: date, test_start: date
) -> dict[str, Any]:
    if (validation_start, test_start) != (date(2024, 1, 1), date(2025, 1, 1)):
        raise ValueError("interval diagnostics require the accepted temporal split")
    _require_columns(cohort, Path("cohort"), OUTPUT_COLUMNS)
    dates = pd.to_datetime(cohort["sale_date"], format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ValueError("cohort contains invalid sale dates")
    expected = pd.Series("train", index=cohort.index)
    expected.loc[dates >= pd.Timestamp(validation_start)] = "validation"
    expected.loc[dates >= pd.Timestamp(test_start)] = "test"
    if not cohort["split"].eq(expected).all():
        raise ValueError("cohort split labels disagree with temporal boundaries")
    train = cohort.loc[cohort["split"].eq("train")].copy()
    validation = cohort.loc[cohort["split"].eq("validation")].copy()
    if train.empty or validation.empty or not cohort["split"].eq("test").any():
        raise ValueError("cohort must contain train, validation, and test rows")
    for part in (train, validation):
        for column in ("price_usd", "beds", "baths", "square_feet", "year_built"):
            part[column] = pd.to_numeric(part[column], errors="coerce")
            values = part[column].to_numpy(dtype=float)
            if not np.isfinite(values).all() or (
                column == "price_usd" and (values <= 0).any()
            ):
                raise ValueError(f"pre-2025 cohort has invalid {column}")
        if not part["property_type"].isin(RESIDENTIAL_TYPES).all():
            raise ValueError("pre-2025 cohort has unsupported property types")
        if not part["zip"].astype("string").isin(STUDY_ZIPS).all():
            raise ValueError("pre-2025 cohort has ZIPs outside the study area")
    model, categories = _fit(train)
    train_predicted = _predict(model, categories, train)
    predicted = _predict(model, categories, validation)
    if (
        not np.isfinite(train_predicted).all()
        or (train_predicted <= 0).any()
        or not np.isfinite(predicted).all()
        or (predicted <= 0).any()
    ):
        raise ValueError("predictions must be positive and finite")
    actual = validation["price_usd"].to_numpy(dtype=float)
    calibration = (
        pd.to_datetime(validation["sale_date"], format="%Y-%m-%d")
        .lt(pd.Timestamp(CALIBRATION_END))
        .to_numpy()
    )
    assessment = ~calibration
    if (
        calibration.sum() < SMALL_SLICE_MIN_ROWS
        or assessment.sum() < SMALL_SLICE_MIN_ROWS
    ):
        raise ValueError("each 2024 half needs at least 30 sales")
    predicted_edges = np.quantile(train_predicted, [0.5, 0.9])
    bands = np.digitize(predicted, predicted_edges, right=True)
    zip_codes = validation["zip"].astype("string").to_numpy(dtype=str)
    train_p50 = float(train["price_usd"].quantile(0.5))
    train_p90 = float(train["price_usd"].quantile(0.9))

    candidates: dict[str, Any] = {}
    for name, groups, min_rows in (
        ("global", None, 0),
        ("predicted_band_100", bands, PREDICTED_BAND_MIN_ROWS),
        ("zip_100", zip_codes, ZIP_MIN_ROWS),
        ("zip_60_exploratory", zip_codes, EXPLORATORY_ZIP_MIN_ROWS),
    ):
        lower, upper, support = _candidate_bounds(
            actual, predicted, calibration, groups, min_rows
        )
        assessment_frame = validation.loc[assessment]
        metrics = _assess(
            assessment_frame,
            predicted[assessment],
            lower[assessment],
            upper[assessment],
            train_p50,
            train_p90,
        )
        metrics["by_predicted_price_band"] = _predicted_band_metrics(
            actual[assessment],
            predicted[assessment],
            lower[assessment],
            upper[assessment],
            bands[assessment],
        )
        candidates[name] = {
            "minimum_local_calibration_rows": min_rows,
            "group_support": support,
            "metrics": metrics,
        }
    return {
        "cohort_scope": "eight selected ZIPs inside Durham County boundary",
        "county_wide_supported": False,
        "fixed_point_model": {"config": {**MODEL_CONFIG, "loss": FIXED_LOSS}},
        "scikit_learn_version": sklearn.__version__,
        "training_rows": len(train),
        "calibration_rows": int(calibration.sum()),
        "assessment_rows": int(assessment.sum()),
        "training_price_p50_usd": round(train_p50, 2),
        "training_price_p90_usd": round(train_p90, 2),
        "training_prediction_band_edges_usd": predicted_edges.round(2).tolist(),
        "calibration_period": "January-June 2024",
        "assessment_period": "July-December 2024",
        "method_note": (
            "Previously fixed 9% lower / 1% upper relative tails; groups use only "
            "predicted price or ZIP."
        ),
        "candidates": candidates,
        "serving_interval_approved": False,
        "final_assessment_available": False,
        "selection_note": (
            "Exploratory only. The 2025 outcomes were inspected in an earlier study; "
            "they are not reused here or a fresh final test. No scales are exported."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit 2024 interval slice support")
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
        default=Path("data/processed/interval_slice_diagnostics.json"),
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
        report = diagnose_2024_candidates(cohort, validation_start, test_start)
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
    print(f"Wrote research-only interval diagnostics to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
