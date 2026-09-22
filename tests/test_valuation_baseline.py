from datetime import date

import numpy as np
import pandas as pd
import pytest
from homelens.modeling.baseline import evaluate_baselines


def _cohort() -> pd.DataFrame:
    rows = []
    for index in range(60):
        rows.append(
            {
                "sale_date": "2023-06-01",
                "price_usd": 150000 + index * 1000,
                "beds": 2 + index % 3,
                "baths": 1 + index % 2,
                "square_feet": 900 + index * 15,
                "year_built": 1980 + index % 30,
                "property_type": (
                    "Single Family Residential" if index % 2 else "Townhouse"
                ),
                "zip": "27703" if index % 2 else "27705",
                "split": "train",
                "$/SQUARE FEET": 999999,
            }
        )
    for split, sale_date in (
        ("validation", "2024-06-01"),
        ("test", "2025-03-01"),
    ):
        for index in range(5):
            rows.append(
                {
                    "sale_date": sale_date,
                    "price_usd": 300000 + index * 10000,
                    "beds": 3,
                    "baths": 2,
                    "square_feet": 1500 + index * 50,
                    "year_built": 2000,
                    "property_type": "Condo/Co-op",
                    "zip": "27712",
                    "split": split,
                    "$/SQUARE FEET": -999999,
                }
            )
    return pd.DataFrame(rows)


def test_baseline_uses_only_training_rows_and_approved_predictors() -> None:
    cohort = _cohort()
    report = evaluate_baselines(cohort, date(2024, 1, 1), date(2025, 1, 1))

    assert report["split_counts"] == {"train": 60, "validation": 5, "test": 5}
    assert report["training_median_usd"] == 179500
    assert report["predictor_columns"] == [
        "beds",
        "baths",
        "square_feet",
        "year_built",
        "property_type",
        "zip",
    ]
    assert report["training_only_categories"]["zip"] == ["27703", "27705"]
    assert report["county_boundary_validated"] is False
    assert report["small_slice_min_rows"] == 30
    for model in ("training_median", "hist_gradient_boosting"):
        for split in ("validation", "test"):
            result = report["evaluations"][model][split]
            assert result["overall"]["rows"] == 5
            assert result["overall"]["mae_usd"] >= 0
            assert result["overall"]["p90_absolute_error_usd"] >= 0
            assert result["overall"]["small_slice"] is True
            assert result["by_zip"]["27712"]["rows"] == 5
            assert result["by_property_type"]["Condo/Co-op"]["rows"] == 5
            assert result["by_zip_and_property_type"] == [
                {
                    "zip": "27712",
                    "property_type": "Condo/Co-op",
                    "rows": 5,
                    "small_slice": True,
                }
            ]
            assert result["error_concentration"] == {
                "rows": 5,
                "small_slice": True,
            }

    cohort.loc[cohort["split"].eq("validation"), "price_usd"] = 99999999
    changed = evaluate_baselines(cohort, date(2024, 1, 1), date(2025, 1, 1))
    assert changed["training_median_usd"] == report["training_median_usd"]


def test_baseline_rejects_temporal_mislabeling() -> None:
    cohort = _cohort()
    cohort.loc[0, "split"] = "test"

    with pytest.raises(ValueError, match="split labels disagree"):
        evaluate_baselines(cohort, date(2024, 1, 1), date(2025, 1, 1))


def test_baseline_rejects_nonfinite_target() -> None:
    cohort = _cohort()
    cohort["price_usd"] = cohort["price_usd"].astype(float)
    cohort.loc[0, "price_usd"] = np.inf

    with pytest.raises(ValueError, match="nonfinite price_usd"):
        evaluate_baselines(cohort, date(2024, 1, 1), date(2025, 1, 1))


def test_tail_diagnostics_use_training_thresholds_and_aggregate_errors() -> None:
    cohort = _cohort()
    train = cohort.loc[cohort["split"].eq("train")]
    evaluation_rows = cohort.loc[cohort["split"].ne("train")]
    repeated = pd.concat([evaluation_rows] * 24, ignore_index=True)
    for split in ("validation", "test"):
        indices = repeated.index[repeated["split"].eq(split)]
        repeated.loc[indices, "price_usd"] = (
            [100000] * 40 + [190000] * 40 + [500000] * 40
        )
    expanded = pd.concat([train, repeated], ignore_index=True)

    report = evaluate_baselines(expanded, date(2024, 1, 1), date(2025, 1, 1))
    assert report["training_price_quantiles_usd"] == {"p50": 179500, "p90": 203100}
    result = report["evaluations"]["hist_gradient_boosting"]["test"]
    bands = result["by_training_price_band"]
    assert {name: band["rows"] for name, band in bands.items()} == {
        "at_or_below_train_p50": 40,
        "train_p50_to_p90": 40,
        "above_train_p90": 40,
    }
    assert bands["above_train_p90"]["mean_signed_error_usd"] < 0
    assert sum(
        band["share_absolute_error"] for band in bands.values()
    ) == pytest.approx(1, abs=0.0002)
    assert result["by_zip_and_property_type"][0]["rows"] == 120
    assert {
        row["training_price_band"]: row["rows"]
        for row in result["by_zip_property_type_and_training_price_band"]
    } == {
        "at_or_below_train_p50": 40,
        "train_p50_to_p90": 40,
        "above_train_p90": 40,
    }
    assert result["error_concentration"]["top_5pct_rows"] == 6
    assert 0 < result["error_concentration"]["share_squared_error"] <= 1
