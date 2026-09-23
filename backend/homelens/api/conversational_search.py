"""Optional natural-language intent endpoint; it never queries the catalog."""

from __future__ import annotations

from typing import Any, cast

from flask import Blueprint, Response, current_app, jsonify, request

from homelens.adapters.openai_search import SearchProviderError
from homelens.services.conversational_search import (
    ConversationalSearchService,
    InvalidSearchRequest,
    SearchUnavailableError,
)

conversational_search_bp = Blueprint("conversational_search", __name__)


@conversational_search_bp.post("/api/search/interpret")
def interpret_search() -> Response | tuple[Response, int]:
    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) - {
        "query",
        "question",
        "answer",
    }:
        return jsonify(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "Expected a search request.",
                }
            }
        ), 400
    service = cast(
        ConversationalSearchService, current_app.extensions["conversational_search"]
    )
    try:
        result = service.interpret(
            payload.get("query"), payload.get("question"), payload.get("answer")
        )
    except InvalidSearchRequest as exc:
        return jsonify({"error": {"code": "invalid_request", "message": str(exc)}}), 400
    except SearchUnavailableError as exc:
        return jsonify(
            {"error": {"code": "ai_search_unavailable", "message": str(exc)}}
        ), 503
    except SearchProviderError as exc:
        return jsonify(
            {"error": {"code": "ai_search_failed", "message": str(exc)}}
        ), 502
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response
