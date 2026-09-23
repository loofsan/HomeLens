"""Optional sourced provider context for catalog properties."""

from __future__ import annotations

from typing import cast

from flask import Blueprint, Response, current_app, jsonify

from homelens.data.property_repository import CatalogUnavailableError
from homelens.domain.property_context import ProviderRequestError
from homelens.services.property_context import PropertyContextService

context_bp = Blueprint("context", __name__)


def _service() -> PropertyContextService:
    return cast(PropertyContextService, current_app.extensions["property_context"])


@context_bp.errorhandler(CatalogUnavailableError)
def _catalog_unavailable(_error: CatalogUnavailableError) -> tuple[Response, int]:
    return jsonify({"error": {"code": "catalog_unavailable"}}), 503


@context_bp.get("/api/properties/<property_id>/context")
def property_context(property_id: str) -> Response | tuple[Response, int]:
    result = _service().get(property_id)
    if result is None:
        return jsonify({"error": {"code": "property_not_found"}}), 404
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@context_bp.get("/api/properties/<property_id>/street-view/image")
def street_view_image(property_id: str) -> Response | tuple[Response, int]:
    try:
        image = _service().street_view_image(property_id)
    except ProviderRequestError as exc:
        status = 404 if exc.reason in ("not_covered", "not_configured") else 503
        return jsonify({"error": {"code": exc.reason}}), status
    if image is None:
        return jsonify({"error": {"code": "property_not_found"}}), 404
    content, media_type = image
    response = Response(content, mimetype=media_type)
    response.headers["Cache-Control"] = "no-store"
    return response
