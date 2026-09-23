from datetime import date

import numpy as np
import pandas as pd
import pytest
from homelens.modeling.interval_slice_diagnostics import (
    _candidate_bounds,
    _upper_rank_from_max,
    diagnose_2024_candidates,
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


def test_upper_tail_rank_exposes_extreme_group_quantiles() -> None:
    assert _upper_rank_from_max(73) == 0
    assert _upper_rank_from_max(174) == 0
    assert _upper_rank_from_max(560) == 4
    with pytest.raises(ValueError, match="nonempty"):
        _upper_rank_from_max(0)


def test_small_groups_fall_back_to_global_scales() -> None:
    actual = np.linspace(200000, 400000, 80)
    predicted = np.full(80, 300000.0)
    calibration = np.array([True] * 40 + [False] * 40)
    groups = np.array(["27701"] * 20 + ["27707"] * 60)
    global_lower, global_upper, _ = _candidate_bounds(
        actual, predicted, calibration, None, 0
    )
    lower, upper, support = _candidate_bounds(
        actual, predicted, calibration, groups, 60
    )
    np.testing.assert_array_equal(lower, global_lower)
    np.testing.assert_array_equal(upper, global_upper)
    assert support["27701"]["local_calibration"] is False
    assert support["27707"]["calibration_rows"] == 20


def test_2025_targets_cannot_change_candidate_report() -> None:
    cohort = _cohort()
    report = diagnose_2024_candidates(cohort, date(2024, 1, 1), date(2025, 1, 1))
    assert report["calibration_rows"] == 40
    assert report["assessment_rows"] == 40
    assert report["serving_interval_approved"] is False
    assert report["final_assessment_available"] is False
    assert "held_out_test" not in report
    assert (
        report["candidates"]["zip_100"]["group_support"]["27707"]["local_calibration"]
        is False
    )

    changed = cohort.copy()
    changed.loc[changed["split"].eq("test"), "price_usd"] += 1_000_000
    assert (
        diagnose_2024_candidates(changed, date(2024, 1, 1), date(2025, 1, 1)) == report
    )


def test_rejects_wrong_split_and_missing_2024_half() -> None:
    with pytest.raises(ValueError, match="accepted temporal split"):
        diagnose_2024_candidates(_cohort(), date(2024, 2, 1), date(2025, 1, 1))
    cohort = _cohort()
    cohort.loc[cohort["sale_date"].eq("2024-09-01"), "sale_date"] = "2024-03-01"
    with pytest.raises(ValueError, match="each 2024 half"):
        diagnose_2024_candidates(cohort, date(2024, 1, 1), date(2025, 1, 1))


def test_rejects_invalid_pre_2025_categories() -> None:
    cohort = _cohort()
    cohort.loc[0, "zip"] = "99999"
    with pytest.raises(ValueError, match="ZIPs outside the study area"):
        diagnose_2024_candidates(cohort, date(2024, 1, 1), date(2025, 1, 1))
