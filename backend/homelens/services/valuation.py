"""Load a trusted offline artifact once and score supported historical sales."""

from __future__ import annotations

import json
import math
import platform
from datetime import date
from pathlib import Path
from typing import Any, cast

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor

from homelens.data.inventory import _file_identity
from homelens.domain.property import CatalogSource, HistoricalSale
from homelens.modeling.artifact_contract import ARTIFACT_VERSION, MODEL_VERSION
from homelens.modeling.baseline import MODEL_CONFIG, _features
from homelens.modeling.county_comparison import FIXED_LOSS


class ValuationUnavailableError(Exception):
    """The configured artifact cannot safely serve predictions."""


class UnsupportedValuationError(Exception):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class ValuationService:
    def __init__(self, artifact_dir: Path) -> None:
        self._model: HistGradientBoostingRegressor | None = None
        self._metadata: dict[str, Any] | None = None
        self._categories: dict[str, list[str]] | None = None
        self._failure = "Valuation artifact is not available. Run the offline export."
        try:
            metadata_path = artifact_dir / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise ValueError("artifact metadata must be an object")
            if (
                metadata.get("artifact_format_version") != ARTIFACT_VERSION
                or metadata.get("model_version") != MODEL_VERSION
                or metadata.get("model_file") != "model.joblib"
                or metadata.get("prediction_interval_available") is not False
                or metadata.get("python_version") != platform.python_version()
                or metadata.get("scikit_learn_version") != sklearn.__version__
                or metadata.get("pandas_version") != pd.__version__
                or metadata.get("numpy_version") != np.__version__
            ):
                raise ValueError("artifact version or runtime is incompatible")
            model_path = artifact_dir / "model.joblib"
            if metadata.get("model_identity") != _file_identity(model_path):
                raise ValueError("artifact model checksum does not match metadata")
            # joblib uses pickle; only load artifacts from a trusted local workspace.
            bundle = joblib.load(model_path)
            if not isinstance(bundle, dict) or not isinstance(
                bundle.get("model"), HistGradientBoostingRegressor
            ):
                raise ValueError("artifact model has an unexpected type")
            if metadata.get("model_config") != {
                **MODEL_CONFIG,
                "loss": FIXED_LOSS,
            } or any(
                bundle["model"].get_params()[key] != value
                for key, value in metadata["model_config"].items()
            ):
                raise ValueError("artifact model configuration is incompatible")
            categories = bundle.get("categories")
            if (
                not isinstance(categories, dict)
                or set(categories) != {"property_type", "zip"}
                or any(
                    not isinstance(categories[field], list)
                    or not categories[field]
                    or not all(isinstance(value, str) for value in categories[field])
                    for field in ("property_type", "zip")
                )
            ):
                raise ValueError("artifact categories are invalid")
            if categories != {
                "property_type": metadata.get("supported_property_types"),
                "zip": metadata.get("supported_zips"),
            }:
                raise ValueError("artifact categories disagree with metadata")
            for field in ("source_identity", "boundary_source_identity"):
                if not isinstance(metadata.get(field, {}).get("sha256"), str):
                    raise ValueError("artifact source identity is missing")
            for field in ("train", "test"):
                date.fromisoformat(metadata["split_date_ranges"][field][0])
                date.fromisoformat(metadata["split_date_ranges"][field][1])
            for field in ("beds", "baths", "square_feet", "year_built"):
                low, high = metadata["feature_ranges"][field]
                if (
                    not all(math.isfinite(float(value)) for value in (low, high))
                    or low > high
                ):
                    raise ValueError("artifact feature range is invalid")
        except Exception as exc:
            self._failure = f"Valuation artifact is unavailable or incompatible: {exc}"
            return
        self._model = bundle["model"]
        self._metadata = metadata
        self._categories = cast(dict[str, list[str]], categories)

    def predict(self, record: HistoricalSale, source: CatalogSource) -> dict[str, Any]:
        if source.synthetic:
            raise UnsupportedValuationError(
                "record_kind", "Synthetic demo records cannot be valued."
            )
        if self._model is None or self._metadata is None or self._categories is None:
            raise ValuationUnavailableError(self._failure)
        metadata = self._metadata
        if (
            source.source_sha256 != metadata["source_identity"]["sha256"]
            or source.boundary_sha256 != metadata["boundary_source_identity"]["sha256"]
        ):
            raise ValuationUnavailableError(
                "Catalog source or county boundary differs from the model artifact."
            )
        if record.record_kind != "historical_sale":
            raise UnsupportedValuationError(
                "record_kind", "Only historical sales are supported."
            )
        if record.zip not in self._categories["zip"]:
            raise UnsupportedValuationError(
                "zip", "This ZIP is outside the model study area."
            )
        if record.property_type not in self._categories["property_type"]:
            raise UnsupportedValuationError(
                "property_type", "This property type is outside the model study area."
            )
        earliest = date.fromisoformat(metadata["split_date_ranges"]["train"][0])
        latest = date.fromisoformat(metadata["split_date_ranges"]["test"][1])
        if not earliest <= record.sale_date <= latest:
            raise UnsupportedValuationError(
                "sale_date", "This sale date is outside the model's historical vintage."
            )
        if record.year_built > record.sale_date.year:
            raise UnsupportedValuationError(
                "year_built", "Construction year is later than the sale year."
            )
        values = {
            "beds": record.beds,
            "baths": record.baths,
            "square_feet": record.square_feet,
            "year_built": record.year_built,
        }
        for field, value in values.items():
            low, high = metadata["feature_ranges"][field]
            if not math.isfinite(value) or not low <= value <= high:
                raise UnsupportedValuationError(
                    field, f"{field} is outside the model's training range."
                )
        frame = pd.DataFrame(
            [{**values, "property_type": record.property_type, "zip": record.zip}]
        )
        try:
            predicted = float(
                self._model.predict(_features(frame, self._categories))[0]
            )
        except (ValueError, RuntimeError) as exc:
            raise ValuationUnavailableError("Valuation prediction failed.") from exc
        if not math.isfinite(predicted) or predicted <= 0:
            raise ValuationUnavailableError("Valuation prediction is invalid.")
        return {
            "property_id": record.id,
            "estimated_historical_price_usd": round(predicted, 2),
            "model_version": metadata["model_version"],
            "scope": metadata["geography_scope"],
            "earliest_supported_sale_date": earliest.isoformat(),
            "latest_supported_sale_date": latest.isoformat(),
            "evaluation": {
                "held_out_test_mae_usd": metadata["held_out_test_overall"]["mae_usd"],
                "held_out_test_mean_signed_error_usd": metadata[
                    "held_out_test_overall"
                ]["mean_signed_error_usd"],
            },
            "prediction_interval": None,
            "disclaimer": (
                "Experimental estimate for a historical sale, not a current market "
                "valuation or appraisal. No calibrated interval is available."
            ),
        }
