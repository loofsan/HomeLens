"""Interpret a free-text nearby request as one allow-listed category."""

from __future__ import annotations

from typing import Any, Protocol

from homelens.domain.nearby_intent import NearbyIntent, keyword_categories


class InvalidNearbyRequest(ValueError):
    """Malformed or oversized nearby request."""


class NearbyIntentProvider(Protocol):
    def interpret_nearby(self, query: str) -> NearbyIntent: ...


class NearbyInterpreter:
    def __init__(self, provider: NearbyIntentProvider | None) -> None:
        self._provider = provider

    def interpret(self, query: Any) -> dict[str, Any]:
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 80:
            raise InvalidNearbyRequest("query must contain 2-80 characters")
        text = query.strip()
        matches = keyword_categories(text)
        if len(matches) == 1:
            return {"status": "matched", "category": matches[0], "method": "keyword"}
        if len(matches) > 1:
            return {
                "status": "ambiguous",
                "category": None,
                "method": "keyword",
                "options": matches,
            }
        if self._provider is None:
            return {"status": "no_match", "category": None, "method": None}
        proposal = self._provider.interpret_nearby(text)
        if not isinstance(proposal, NearbyIntent) or proposal.category is None:
            return {"status": "no_match", "category": None, "method": "ai"}
        return {"status": "matched", "category": proposal.category, "method": "ai"}
