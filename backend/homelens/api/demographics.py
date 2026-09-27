"""Prepared census demographics for a catalog sale's ZIP code."""

from __future__ import annotations

from typing import cast

from flask import Blueprint, Response, current_app, jsonify

from homelens.data.property_repository import CatalogUnavailableError
from homelens.services.demographics import (
    DemographicsService,
    DemographicsUnavailableError,
)

demographics_bp = Blueprint("demographics", __name__)


def _service() -> DemographicsService:
    return cast(DemographicsService, current_app.extensions["demographics"])


@demographics_bp.errorhandler(CatalogUnavailableError)
def _catalog_unavailable(_error: CatalogUnavailableError) -> tuple[Response, int]:
    return jsonify({"error": {"code": "catalog_unavailable"}}), 503


@demographics_bp.get("/api/properties/<property_id>/demographics")
def property_demographics(property_id: str) -> Response | tuple[Response, int]:
    try:
        result = _service().get(property_id)
    except DemographicsUnavailableError:
        return (
            jsonify(
                {
                    "error": {
                        "code": "demographics_unavailable",
                        "message": (
                            "Area demographics are not prepared. "
                            "Run the offline ACS ZCTA import."
                        ),
                    }
                }
            ),
            503,
        )
    if result is None:
        return (
            jsonify(
                {
                    "error": {
                        "code": "property_not_found",
                        "message": "Historical sale was not found.",
                    }
                }
            ),
            404,
        )
    return jsonify(result)
