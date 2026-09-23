"""Source-aware context around a historical sale, never an active-listing claim."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class ContextSection(TypedDict):
    status: Literal["available", "unavailable", "error"]
    reason: str | None
    source: str
    coverage: dict[str, Any]
    data: dict[str, Any] | None


class ProviderRequestError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def section(
    status: Literal["available", "unavailable", "error"],
    source: str,
    coverage: dict[str, Any],
    *,
    reason: str | None = None,
    data: dict[str, Any] | None = None,
) -> ContextSection:
    return {
        "status": status,
        "reason": reason,
        "source": source,
        "coverage": coverage,
        "data": data,
    }
