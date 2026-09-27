"""Validate an interpreted request before it can touch deterministic search."""

from __future__ import annotations

import re
from typing import Any, Protocol

from homelens.domain.search_intent import SearchIntent

UNSUPPORTED_PATTERN = re.compile(
    r"\b(?:active listings?|currently (?:listed|for sale)|for sale|schools?|"
    r"crime|safe(?:st)? neighborhoods?|pools?|near(?:by)?|within \d+ miles?|"
    r"acres?|lot size|"
    r"chapel hill|sql|dump (?:all |the )?data|ignore (?:your |previous )?"
    r"instructions?)\b",
    re.IGNORECASE,
)
VAGUE_PRICE_PATTERN = re.compile(
    r"\b(?:around|about|roughly|approximately)\s+\$?\s*\d", re.IGNORECASE
)


SUPPORTED_MESSAGE = (
    "This search supports historical sales by price, minimum beds or baths, ZIP, "
    "home type, square feet, and year built. That request includes an "
    "unsupported condition."
)
DEFAULT_QUESTION = "Which price, beds, baths, ZIP, home type, size, or year built?"
RANGES = (
    ("min_price", "max_price", "Should the minimum price be lower than the maximum?"),
    ("min_sqft", "max_sqft", "Should the minimum size be smaller than the maximum?"),
    (
        "min_year_built",
        "max_year_built",
        "Should the earliest year built come before the latest?",
    ),
)


class InvalidSearchRequest(ValueError):
    """Malformed or oversized user request."""


class SearchUnavailableError(Exception):
    """No model provider is configured for optional search."""


class IntentProvider(Protocol):
    def interpret(
        self, query: str, question: str | None, answer: str | None
    ) -> SearchIntent: ...


def _text(value: Any, name: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise InvalidSearchRequest(
            f"{name} must contain {minimum}-{maximum} characters"
        )
    return value.strip()


class ConversationalSearchService:
    def __init__(self, provider: IntentProvider | None) -> None:
        self._provider = provider

    def interpret(
        self,
        query: Any,
        question: Any = None,
        answer: Any = None,
    ) -> dict[str, Any]:
        request = _text(query, "query", 5, 400)
        if (question is None) != (answer is None):
            raise InvalidSearchRequest("question and answer must be supplied together")
        previous_question = (
            _text(question, "question", 5, 200) if question is not None else None
        )
        clarification = _text(answer, "answer", 1, 200) if answer is not None else None

        combined = request + " " + (clarification or "")
        if UNSUPPORTED_PATTERN.search(combined):
            return {
                "status": "unsupported",
                "filters": {},
                "question": None,
                "message": (SUPPORTED_MESSAGE),
            }
        if VAGUE_PRICE_PATTERN.search(combined) and clarification is None:
            return {
                "status": "clarify",
                "filters": {},
                "question": "What minimum or maximum price should I use?",
                "message": None,
            }
        if self._provider is None:
            raise SearchUnavailableError(
                "AI search is not configured. Use the filters below."
            )

        proposal = self._provider.interpret(request, previous_question, clarification)
        if not isinstance(proposal, SearchIntent):
            raise SearchUnavailableError("AI search returned an invalid response.")
        if proposal.status == "unsupported" or proposal.unsupported:
            return {
                "status": "unsupported",
                "filters": {},
                "question": None,
                "message": (SUPPORTED_MESSAGE),
            }
        if proposal.status == "clarify":
            asked = (proposal.question or "").strip()
            return {
                "status": "clarify",
                "filters": {},
                "question": asked[:200] if asked else DEFAULT_QUESTION,
                "message": None,
            }
        if proposal.question and proposal.question.strip():
            return {
                "status": "clarify",
                "filters": {},
                "question": proposal.question.strip()[:200],
                "message": None,
            }
        filters = proposal.filters.model_dump(exclude_none=True)
        if not filters:
            return {
                "status": "clarify",
                "filters": {},
                "question": DEFAULT_QUESTION,
                "message": None,
            }
        for low, high, question in RANGES:
            if low in filters and high in filters and filters[low] > filters[high]:
                return {
                    "status": "clarify",
                    "filters": {},
                    "question": question,
                    "message": None,
                }
        return {
            "status": "ready",
            "filters": filters,
            "question": None,
            "message": None,
        }
