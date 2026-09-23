"""Export the fixed county-verified valuation model outside the request path."""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn

from homelens.data.inventory import _file_identity, _read_csv, _require_columns
from homelens.data.prepare import OUTPUT_COLUMNS
from homelens.modeling.artifact_contract import ARTIFACT_VERSION, MODEL_VERSION
from homelens.modeling.baseline import (
    MODEL_CONFIG,
    NUMERIC_COLUMNS,
    _read_audit,
    _validate_cohort,
)
from homelens.modeling.county_comparison import (
    FIXED_LOSS,
    _aggregate,
    _fit,
    _predict,
)


def export_model(
    cohort_path: Path,
    audit_path: Path,
    comparison_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    validation_start, test_start, audit = _read_audit(audit_path)
    cohort = _read_csv(cohort_path, ("sale_date", "property_type", "zip", "split"))
    _require_columns(cohort, cohort_path, OUTPUT_COLUMNS)
    cohort = _validate_cohort(cohort, validation_start, test_start)
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    if (
        audit.get("rules", {}).get("county_boundary_validated") is not True
        or audit.get("prepared_rows") != len(cohort)
        or audit.get("split_counts") != cohort["split"].value_counts().to_dict()
        or comparison.get("selected_cohort_identity") != _file_identity(cohort_path)
        or comparison.get("selected_audit_identity") != _file_identity(audit_path)
        or comparison.get("boundary_source_identity")
        != audit.get("boundary_source_identity")
        or comparison.get("fixed_model_config") != {**MODEL_CONFIG, "loss": FIXED_LOSS}
        or comparison.get("scikit_learn_version") != sklearn.__version__
    ):
        raise ValueError("cohort, audit, or accepted comparison is inconsistent")

    model, categories = _fit(cohort)
    validation = cohort.loc[cohort["split"].eq("validation")]
    test = cohort.loc[cohort["split"].eq("test")]
    for name, frame, expected in (
        (
            "validation",
            validation,
            comparison["validation"]["selected_model_on_common_sales"]["overall"],
        ),
        ("test", test, comparison["held_out_test"]["selected_model"]["overall"]),
    ):
        observed = _aggregate(frame, _predict(model, categories, frame))["overall"]
        if observed != expected:
            raise ValueError(f"{name} metrics differ from accepted comparison")

    train = cohort.loc[cohort["split"].eq("train")]
    metadata: dict[str, Any] = {
        "artifact_format_version": ARTIFACT_VERSION,
        "model_version": MODEL_VERSION,
        "model_file": "model.joblib",
        "model_config": {**MODEL_CONFIG, "loss": FIXED_LOSS},
        "python_version": platform.python_version(),
        "scikit_learn_version": sklearn.__version__,
        "pandas_version": pd.__version__,
        "numpy_version": np.__version__,
        "cohort_identity": _file_identity(cohort_path),
        "cohort_audit_identity": _file_identity(audit_path),
        "comparison_identity": _file_identity(comparison_path),
        "source_identity": audit["source_identity"],
        "boundary_source_identity": audit["boundary_source_identity"],
        "split_boundaries": audit["split_boundaries"],
        "split_counts": audit["split_counts"],
        "split_date_ranges": audit["split_date_ranges"],
        "supported_zips": categories["zip"],
        "supported_property_types": categories["property_type"],
        "feature_ranges": {
            column: [float(train[column].min()), float(train[column].max())]
            for column in NUMERIC_COLUMNS
        },
        "validation_overall": comparison["validation"][
            "selected_model_on_common_sales"
        ]["overall"],
        "held_out_test_overall": comparison["held_out_test"]["selected_model"][
            "overall"
        ],
        "geography_scope": "selected eight ZIPs inside Durham County boundary",
        "record_kind": "historical_sale",
        "prediction_interval_available": False,
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    model_path = output_dir / metadata["model_file"]
    joblib.dump({"model": model, "categories": categories}, model_path)
    metadata["model_identity"] = _file_identity(model_path)
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Export fixed HomeLens valuation v1")
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
    parser.add_argument("--output", type=Path, default=Path("models/valuation_v1"))
    args = parser.parse_args()
    try:
        metadata = export_model(args.cohort, args.audit, args.comparison, args.output)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Exported {metadata['model_version']} to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
