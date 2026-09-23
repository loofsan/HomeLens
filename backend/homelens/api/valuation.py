"""Historical-sale valuation endpoint with explicit support failures."""

from __future__ import annotations

from typing import cast

from flask import Blueprint, Response, current_app, jsonify

from homelens.data.property_repository import CatalogUnavailableError
from homelens.services.property_search import PropertySearchService
from homelens.services.valuation import (
    UnsupportedValuationError,
    ValuationService,
    ValuationUnavailableError,
)

valuation_bp = Blueprint("valuation", __name__)


@valuation_bp.get("/api/properties/<property_id>/valuation")
def get_valuation(property_id: str) -> Response | tuple[Response, int]:
    search = cast(PropertySearchService, current_app.extensions["property_search"])
    service = cast(ValuationService, current_app.extensions["valuation"])
    try:
        record, source = search.get(property_id)
        if record is None:
            return jsonify(
                {
                    "error": {
                        "code": "property_not_found",
                        "message": "Historical sale was not found.",
                    }
                }
            ), 404
        return jsonify(service.predict(record, source))
    except CatalogUnavailableError:
        return jsonify(
            {
                "error": {
                    "code": "catalog_unavailable",
                    "message": "Historical sales catalog is unavailable.",
                }
            }
        ), 503
    except ValuationUnavailableError as exc:
        return jsonify(
            {"error": {"code": "valuation_unavailable", "message": str(exc)}}
        ), 503
    except UnsupportedValuationError as exc:
        return jsonify(
            {
                "error": {
                    "code": "valuation_unsupported",
                    "field": exc.field,
                    "message": str(exc),
                }
            }
        ), 422
