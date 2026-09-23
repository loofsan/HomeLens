import json
import platform
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
import sklearn
from homelens import create_app
from homelens.data.inventory import _file_identity
from homelens.data.property_catalog import write_catalog
from homelens.domain.property import HistoricalSale
from homelens.modeling.baseline import MODEL_CONFIG
from homelens.modeling.county_comparison import FIXED_LOSS, _fit, compare_county_cohorts
from homelens.modeling.export import export_model
from homelens.services.valuation import ValuationService


def _artifact(path: Path) -> None:
    frame = pd.DataFrame(
        [
            {
                "beds": 3.0,
                "baths": 2.0,
                "square_feet": 1200.0 + index,
                "year_built": 1990,
                "property_type": "Townhouse",
                "zip": "27703",
                "price_usd": 350000.0 + index,
                "split": "train",
            }
            for index in range(50)
        ]
    )
    model, categories = _fit(frame)
    path.mkdir()
    model_path = path / "model.joblib"
    joblib.dump({"model": model, "categories": categories}, model_path)
    metadata = {
        "artifact_format_version": 1,
        "model_version": "county-poisson-v1",
        "model_file": "model.joblib",
        "model_config": {**MODEL_CONFIG, "loss": FIXED_LOSS},
        "model_identity": _file_identity(model_path),
        "prediction_interval_available": False,
        "python_version": platform.python_version(),
        "scikit_learn_version": sklearn.__version__,
        "pandas_version": pd.__version__,
        "numpy_version": np.__version__,
        "source_identity": {"sha256": "a" * 64},
        "boundary_source_identity": {"sha256": "b" * 64},
        "supported_property_types": categories["property_type"],
        "supported_zips": categories["zip"],
        "split_date_ranges": {
            "train": ["2020-01-01", "2023-12-31"],
            "test": ["2025-01-01", "2025-05-20"],
        },
        "feature_ranges": {
            "beds": [0.0, 8.0],
            "baths": [1.0, 10.5],
            "square_feet": [383.0, 10129.0],
            "year_built": [1890, 2023],
        },
        "geography_scope": "selected eight ZIPs inside Durham County boundary",
        "held_out_test_overall": {
            "mae_usd": 81625.74,
            "mean_signed_error_usd": -56951.48,
        },
    }
    (path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def _app(tmp_path: Path):  # type: ignore[no-untyped-def]
    artifact = tmp_path / "artifact"
    _artifact(artifact)
    database = tmp_path / "catalog.sqlite3"
    records = [
        HistoricalSale(
            id="sale_" + key * 32,
            sale_date=date(2024, 6, 1),
            sold_price_usd=350000.0,
            beds=beds,
            baths=2.0,
            square_feet=1200.0,
            year_built=1990,
            property_type="Townhouse",
            address=f"{key} Main St",
            city="Durham",
            state="NC",
            zip=zip_code,
            latitude=36.0,
            longitude=-79.0,
            source_url=None,
        )
        for key, beds, zip_code in (
            ("a", 3.0, "27703"),
            ("b", 9.0, "27703"),
            ("c", 3.0, "27517"),
        )
    ]
    write_catalog(
        database,
        records,
        {
            "imported_rows": len(records),
            "source_identity": {"sha256": "a" * 64},
            "boundary_source_identity": {"sha256": "b" * 64},
            "sale_date_range": ["2024-06-01", "2024-06-01"],
        },
    )
    return create_app(
        {
            "TESTING": True,
            "PROPERTY_CATALOG_PATH": database,
            "VALUATION_ARTIFACT_PATH": artifact,
        }
    )


def test_valuation_endpoint_and_explicit_support_failures(tmp_path: Path) -> None:
    client = _app(tmp_path).test_client()
    supported = client.get("/api/properties/sale_" + "a" * 32 + "/valuation")
    assert supported.status_code == 200
    payload = supported.get_json()
    assert payload["estimated_historical_price_usd"] > 0
    assert payload["prediction_interval"] is None
    assert payload["model_version"] == "county-poisson-v1"
    assert payload["earliest_supported_sale_date"] == "2020-01-01"

    out_of_range = client.get("/api/properties/sale_" + "b" * 32 + "/valuation")
    assert out_of_range.status_code == 422
    assert out_of_range.get_json()["error"]["field"] == "beds"
    outside_zip = client.get("/api/properties/sale_" + "c" * 32 + "/valuation")
    assert outside_zip.status_code == 422
    assert outside_zip.get_json()["error"]["field"] == "zip"
    missing = client.get("/api/properties/sale_" + "d" * 32 + "/valuation")
    assert missing.status_code == 404


def test_artifact_integrity_and_catalog_drift_fail_closed(tmp_path: Path) -> None:
    app = _app(tmp_path)
    artifact = tmp_path / "artifact"
    metadata_path = artifact / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["source_identity"]["sha256"] = "c" * 64
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    drifted = create_app(
        {
            "TESTING": True,
            "PROPERTY_CATALOG_PATH": tmp_path / "catalog.sqlite3",
            "VALUATION_ARTIFACT_PATH": artifact,
        }
    )
    response = drifted.test_client().get(
        "/api/properties/sale_" + "a" * 32 + "/valuation"
    )
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "valuation_unavailable"

    metadata["source_identity"]["sha256"] = "a" * 64
    metadata["model_identity"]["sha256"] = "0" * 64
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    broken = ValuationService(artifact)
    assert broken._model is None
    assert app.extensions["valuation"]._model is not None


def test_missing_artifact_keeps_search_available(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.extensions["valuation"] = ValuationService(tmp_path / "missing")
    client = app.test_client()
    assert client.get("/api/properties").status_code == 200
    assert (
        client.get("/api/properties/sale_" + "a" * 32 + "/valuation").status_code == 503
    )


def test_export_reproduces_accepted_report_and_refuses_changed_cohort(
    tmp_path: Path,
) -> None:
    cohort_path = tmp_path / "cohort.csv"
    audit_path = tmp_path / "audit.json"
    comparison_path = tmp_path / "comparison.json"
    frame = pd.DataFrame(
        [
            {
                "sale_date": (
                    "2023-06-01"
                    if index < 50
                    else "2024-06-01"
                    if index < 60
                    else "2025-02-01"
                ),
                "price_usd": 300000.0 + index * 1000,
                "beds": 3.0,
                "baths": 2.0,
                "square_feet": 1200.0 + index,
                "year_built": 1990,
                "property_type": "Townhouse",
                "zip": "27703",
                "split": "train"
                if index < 50
                else "validation"
                if index < 60
                else "test",
            }
            for index in range(70)
        ]
    )
    frame.to_csv(cohort_path, index=False)
    audit = {
        "rules": {"county_boundary_validated": True},
        "prepared_rows": len(frame),
        "split_boundaries": {
            "validation_start": "2024-01-01",
            "test_start": "2025-01-01",
        },
        "split_counts": {"train": 50, "validation": 10, "test": 10},
        "split_date_ranges": {
            "train": ["2023-06-01", "2023-06-01"],
            "validation": ["2024-06-01", "2024-06-01"],
            "test": ["2025-02-01", "2025-02-01"],
        },
        "source_identity": {"sha256": "a" * 64},
        "boundary_source_identity": {"sha256": "b" * 64},
    }
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    comparison = compare_county_cohorts(
        frame, frame, date(2024, 1, 1), date(2025, 1, 1)
    )
    comparison["selected_cohort_identity"] = _file_identity(cohort_path)
    comparison["selected_audit_identity"] = _file_identity(audit_path)
    comparison["boundary_source_identity"] = audit["boundary_source_identity"]
    comparison_path.write_text(json.dumps(comparison), encoding="utf-8")
    output = tmp_path / "versioned"
    metadata = export_model(cohort_path, audit_path, comparison_path, output)
    assert metadata["model_version"] == "county-poisson-v1"
    assert metadata["prediction_interval_available"] is False
    assert ValuationService(output)._model is not None
    with pytest.raises(FileExistsError):
        export_model(cohort_path, audit_path, comparison_path, output)
    frame.loc[0, "price_usd"] = 1.0
    frame.to_csv(cohort_path, index=False)
    with pytest.raises(ValueError, match="inconsistent"):
        export_model(cohort_path, audit_path, comparison_path, tmp_path / "changed")


def test_valuation_artifact_path_can_use_local_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VALUATION_ARTIFACT_PATH", str(tmp_path))
    app = create_app()
    assert app.config["VALUATION_ARTIFACT_PATH"] == str(tmp_path)
