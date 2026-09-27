"""Index-adjusted value history for a catalog sale."""

from __future__ import annotations

from typing import cast

from flask import Blueprint, Response, current_app, jsonify

from homelens.data.property_repository import CatalogUnavailableError
from homelens.services.value_trend import ValueTrendService, ValueTrendUnavailableError

value_trend_bp = Blueprint("value_trend", __name__)


@value_trend_bp.errorhandler(CatalogUnavailableError)
def _catalog_unavailable(_error: CatalogUnavailableError) -> tuple[Response, int]:
    return jsonify({"error": {"code": "catalog_unavailable"}}), 503


@value_trend_bp.get("/api/properties/<property_id>/value-trend")
def value_trend(property_id: str) -> Response | tuple[Response, int]:
    service = cast(ValueTrendService, current_app.extensions["value_trend"])
    try:
        result = service.get(property_id)
    except ValueTrendUnavailableError:
        return (
            jsonify(
                {
                    "error": {
                        "code": "value_trend_unavailable",
                        "message": (
                            "The ZIP value index is not prepared. "
                            "Run the offline index preparation."
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
