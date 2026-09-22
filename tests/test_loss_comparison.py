from datetime import date

import numpy as np
import pandas as pd
from homelens.modeling.loss_comparison import (
    _choose_loss,
    _interval_check,
    compare_losses,
)


def test_loss_choice_uses_supported_high_price_and_overall_mae() -> None:
    actual = np.full(40, 100.0)
    reference = np.full(40, 200.0)
    candidate = np.full(40, 180.0)
    high = np.array([True] * 30 + [False] * 10)

    assert (
        _choose_loss(actual, reference, candidate, high)["selected_loss"] == "poisson"
    )
    candidate[-10:] = 300.0
    assert (
        _choose_loss(actual, reference, candidate, high)["selected_loss"]
        == "absolute_error"
    )
    sparse = _choose_loss(actual, reference, candidate, np.zeros(40, dtype=bool))
    assert sparse["selected_loss"] == "absolute_error"
    assert sparse["reference_high_price_mae_usd"] is None


def test_interval_check_exposes_high_price_undercoverage() -> None:
    validation = pd.DataFrame(
        {
            "sale_date": ["2024-03-01"] * 30 + ["2024-09-01"] * 30,
            "price_usd": [100.0] * 30 + [200.0] * 30,
        }
    )
    result = _interval_check(validation, np.full(60, 100.0), 150.0, date(2024, 7, 1))

    assert result["half_width_usd"] == 0
    assert result["assessment_coverage"] == 0
    assert result["high_price_coverage"] == 0
    assert result["high_price_assessment_rows"] == 30


def _cohort() -> pd.DataFrame:
    rows = []
    for split, count, sale_date in (
        ("train", 80, "2023-06-01"),
        ("validation", 40, "2024-03-01"),
        ("validation", 40, "2024-09-01"),
        ("test", 40, "2025-03-01"),
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


def test_test_target_cannot_change_validation_selection() -> None:
    cohort = _cohort()
    original = compare_losses(cohort, date(2024, 1, 1), date(2025, 1, 1))
    cohort.loc[cohort["split"].eq("test"), "price_usd"] *= 10
    changed = compare_losses(cohort, date(2024, 1, 1), date(2025, 1, 1))

    assert changed["validation_decision"] == original["validation_decision"]
    assert (
        changed["validation_interval_checks"] == original["validation_interval_checks"]
    )
    assert changed["final_test_evaluations"] != original["final_test_evaluations"]
    assert "sale_date" not in original["final_test_evaluations"]
