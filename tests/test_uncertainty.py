from datetime import date

import numpy as np
import pandas as pd
import pytest
from homelens.modeling.uncertainty import (
    _assess,
    _calibrate,
    _conformal_quantile,
    assess_fixed_interval,
)


def _cohort() -> pd.DataFrame:
    rows = []
    for split, sale_date, count in (
        ("train", "2023-06-01", 80),
        ("validation", "2024-03-01", 40),
        ("validation", "2024-09-01", 40),
        ("test", "2025-03-01", 40),
    ):
        for index in range(count):
            rows.append(
                {
                    "split": split,
                    "sale_date": sale_date,
                    "price_usd": 200000 + index * 8000,
                    "beds": 2 + index % 3,
                    "baths": 1 + index % 2,
                    "square_feet": 900 + index * 20,
                    "year_built": 1980 + index % 30,
                    "property_type": "Single Family Residential",
                    "zip": "27707",
                }
            )
    return pd.DataFrame(rows)


def test_conformal_rank_and_invalid_calibration() -> None:
    assert _conformal_quantile(np.arange(1, 10, dtype=float), 0.9) == 9
    assert _conformal_quantile(np.arange(1, 101, dtype=float), 0.9) == 91
    with pytest.raises(ValueError, match="nonempty and finite"):
        _conformal_quantile(np.array([np.nan]), 0.9)
    with pytest.raises(ValueError, match="positive and finite"):
        _calibrate(np.ones(30), np.zeros(30))


def test_small_slice_suppresses_coverage_and_width() -> None:
    cohort = _cohort().iloc[:20]
    metrics = _assess(
        cohort,
        np.full(len(cohort), 300000.0),
        np.full(len(cohort), 200000.0),
        np.full(len(cohort), 400000.0),
        300000,
        600000,
    )
    assert metrics["overall"] == {"rows": 20, "small_slice": True}
    assert metrics["by_zip"]["27707"] == {"rows": 20, "small_slice": True}


def test_held_out_targets_do_not_change_method_or_validation_assessment() -> None:
    cohort = _cohort()
    report = assess_fixed_interval(cohort, date(2024, 1, 1), date(2025, 1, 1))
    assert report["method"]["upper_tail"] == 0.01
    assert report["fixed_point_model"]["config"]["loss"] == "poisson"
    assert report["validation_assessment"]["calibration_rows"] == 40
    assert report["held_out_test"]["calibration_rows"] == 80
    assert report["serving_interval_approved"] is False

    changed = cohort.copy()
    changed.loc[changed["split"].eq("test"), "price_usd"] += 1_000_000
    changed_report = assess_fixed_interval(changed, date(2024, 1, 1), date(2025, 1, 1))
    assert changed_report["method"] == report["method"]
    assert changed_report["validation_assessment"] == report["validation_assessment"]
    assert changed_report["held_out_test"] != report["held_out_test"]


def test_rejects_wrong_split_boundaries() -> None:
    with pytest.raises(ValueError, match="accepted temporal split"):
        assess_fixed_interval(_cohort(), date(2024, 2, 1), date(2025, 1, 1))
