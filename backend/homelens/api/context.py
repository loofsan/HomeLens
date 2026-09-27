"""Optional sourced provider context for catalog properties."""

from __future__ import annotations

from typing import cast

from flask import Blueprint, Response, current_app, jsonify, request

from homelens.adapters.openai_search import SearchProviderError
from homelens.data.property_repository import CatalogUnavailableError
from homelens.domain.property_context import (
    NearbyQuery,
    NearbyQueryError,
    ProviderRequestError,
)
from homelens.services.nearby_interpreter import (
    InvalidNearbyRequest,
    NearbyInterpreter,
)
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


@context_bp.get("/api/properties/<property_id>/context/nearby")
def nearby_places(property_id: str) -> Response | tuple[Response, int]:
    try:
        query = NearbyQuery.parse(
            request.args.get("category"), request.args.get("radius_m")
        )
    except NearbyQueryError as exc:
        return (
            jsonify(
                {
                    "error": {
                        "code": "invalid_query",
                        "field": exc.field,
                        "message": str(exc),
                    }
                }
            ),
            400,
        )
    result = _service().nearby(property_id, query)
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
        status = (
            422
            if exc.reason == "synthetic_demo"
            else 404
            if exc.reason in ("not_covered", "not_configured")
            else 503
        )
        return jsonify({"error": {"code": exc.reason}}), status
    if image is None:
        return jsonify({"error": {"code": "property_not_found"}}), 404
    content, media_type = image
    response = Response(content, mimetype=media_type)
    response.headers["Cache-Control"] = "no-store"
    return response


@context_bp.post("/api/nearby/interpret")
def interpret_nearby() -> Response | tuple[Response, int]:
    if request.content_length is not None and request.content_length > 1024:
        return jsonify({"error": {"code": "request_too_large"}}), 413
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"query"}:
        return (
            jsonify(
                {
                    "error": {
                        "code": "invalid_request",
                        "message": "Expected a nearby request.",
                    }
                }
            ),
            400,
        )
    interpreter = cast(NearbyInterpreter, current_app.extensions["nearby_interpreter"])
    try:
        result = interpreter.interpret(payload["query"])
    except InvalidNearbyRequest as exc:
        return jsonify({"error": {"code": "invalid_request", "message": str(exc)}}), 400
    except SearchProviderError as exc:
        return jsonify(
            {"error": {"code": "ai_search_failed", "message": str(exc)}}
        ), 502
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response
