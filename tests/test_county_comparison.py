from datetime import date

import pandas as pd
import pytest
from homelens.modeling.county_comparison import compare_county_cohorts


def _cohorts() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for split, sale_date, count in (
        ("train", "2023-06-01", 80),
        ("validation", "2024-06-01", 40),
        ("test", "2025-03-01", 20),
    ):
        for index in range(count):
            rows.append(
                {
                    "sale_date": sale_date,
                    "price_usd": 180000 + index * 2500,
                    "beds": 2 + index % 3,
                    "baths": 1 + index % 2,
                    "square_feet": 900 + index * 20,
                    "year_built": 1980 + index % 30,
                    "property_type": (
                        "Single Family Residential" if index % 2 else "Townhouse"
                    ),
                    "zip": "27703" if index % 2 else "27705",
                    "split": split,
                }
            )
    original = pd.DataFrame(rows)
    selected = original.drop(index=original.index[::7]).reset_index(drop=True)
    return original, selected


def test_comparison_uses_common_validation_and_reserves_test_for_final_report() -> None:
    original, selected = _cohorts()

    report = compare_county_cohorts(
        original, selected, date(2024, 1, 1), date(2025, 1, 1)
    )

    assert report["county_boundary_validated"] is True
    assert report["county_wide_supported"] is False
    assert report["fixed_loss"] == "poisson"
    assert (
        report["validation"]["original_model_on_full_zip_scope"]["overall"]["rows"]
        == 40
    )
    assert (
        report["validation"]["original_model_on_common_sales"]["overall"]["rows"]
        == selected["split"].eq("validation").sum()
    )
    assert (
        report["validation"]["selected_model_on_common_sales"]["overall"]["rows"]
        == selected["split"].eq("validation").sum()
    )
    assert (
        report["held_out_test"]["selected_model"]["overall"]["rows"]
        == selected["split"].eq("test").sum()
    )

    changed_original = original.copy()
    changed_original.loc[changed_original["split"].eq("test"), "price_usd"] += 1_000_000
    changed = selected.copy()
    changed.loc[changed["split"].eq("test"), "price_usd"] += 1_000_000
    changed_report = compare_county_cohorts(
        changed_original, changed, date(2024, 1, 1), date(2025, 1, 1)
    )

    assert changed_report["validation"] == report["validation"]
    assert (
        changed_report["held_out_test"]["selected_model"]["overall"]["mae_usd"]
        != report["held_out_test"]["selected_model"]["overall"]["mae_usd"]
    )


def test_rejects_selected_rows_not_in_original_cohort() -> None:
    original, selected = _cohorts()
    selected.loc[0, "price_usd"] = 999_999

    with pytest.raises(ValueError, match="rows outside ZIP cohort"):
        compare_county_cohorts(original, selected, date(2024, 1, 1), date(2025, 1, 1))
