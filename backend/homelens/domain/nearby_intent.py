"""Map a short free-text place request to one allow-listed nearby category."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

NearbyCategory = Literal[
    "everyday",
    "schools",
    "childcare",
    "parks",
    "grocery",
    "restaurants",
    "bars",
    "shopping",
    "health",
    "libraries",
    "fitness",
    "transit",
]

KEYWORDS: dict[str, tuple[str, ...]] = {
    "schools": ("school", "elementary", "middle school", "high school", "academy"),
    "childcare": (
        "daycare",
        "day care",
        "childcare",
        "child care",
        "preschool",
        "pre-k",
        "nursery",
    ),
    "parks": ("park", "playground", "dog park", "green space"),
    "grocery": ("grocery", "groceries", "supermarket", "food store"),
    "restaurants": ("restaurant", "dining", "cafe", "café", "coffee", "brunch"),
    "bars": ("bar", "pub", "brewery", "nightlife"),
    "shopping": ("mall", "shopping"),
    "health": ("hospital", "pharmacy", "drugstore", "drug store", "emergency room"),
    "libraries": ("library", "libraries"),
    "fitness": ("gym", "fitness", "workout"),
    "transit": ("bus", "transit", "train station", "bus station"),
}
PATTERNS = {
    category: re.compile(
        r"\b(?:" + "|".join(re.escape(word) for word in words) + r")(?:e?s)?\b",
        re.IGNORECASE,
    )
    for category, words in KEYWORDS.items()
}


def keyword_categories(text: str) -> list[str]:
    """Categories whose keywords appear in the text, in allow-list order."""
    return [category for category, pattern in PATTERNS.items() if pattern.search(text)]


class NearbyIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    category: NearbyCategory | None
