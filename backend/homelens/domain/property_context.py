"""Source-aware context around a historical sale, never an active-listing claim."""

from __future__ import annotations

from dataclasses import dataclass
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


NEARBY_CATEGORIES: dict[str, tuple[str, ...]] = {
    "everyday": ("supermarket", "park", "school", "pharmacy"),
    "schools": ("primary_school", "secondary_school", "school"),
    "childcare": ("child_care_agency", "preschool"),
    "parks": ("park", "playground", "dog_park"),
    "grocery": ("supermarket", "grocery_store"),
    "restaurants": ("restaurant", "cafe"),
    "bars": ("bar",),
    "shopping": ("shopping_mall",),
    "health": ("hospital", "pharmacy"),
    "libraries": ("library",),
    "fitness": ("gym",),
    "transit": ("transit_station", "bus_station"),
}
NEARBY_RADII_M: tuple[int, ...] = (800, 1500, 3000, 5000)
DEFAULT_NEARBY_CATEGORY = "everyday"
DEFAULT_NEARBY_RADIUS_M = 1500


class NearbyQueryError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True, slots=True)
class NearbyQuery:
    """A validated nearby-places request drawn from fixed allow-lists."""

    category: str = DEFAULT_NEARBY_CATEGORY
    radius_m: int = DEFAULT_NEARBY_RADIUS_M

    def __post_init__(self) -> None:
        if self.category not in NEARBY_CATEGORIES:
            raise NearbyQueryError(
                "category",
                "Choose one of: " + ", ".join(NEARBY_CATEGORIES) + ".",
            )
        if self.radius_m not in NEARBY_RADII_M:
            raise NearbyQueryError(
                "radius_m",
                "Choose a radius of "
                + ", ".join(str(radius) for radius in NEARBY_RADII_M)
                + " meters.",
            )

    @property
    def types(self) -> tuple[str, ...]:
        return NEARBY_CATEGORIES[self.category]

    @classmethod
    def parse(cls, category: str | None, radius_m: str | None) -> NearbyQuery:
        if radius_m is None or radius_m == "":
            radius = DEFAULT_NEARBY_RADIUS_M
        elif radius_m.isdigit():
            radius = int(radius_m)
        else:
            raise NearbyQueryError("radius_m", "Radius must be a whole number.")
        return cls(category or DEFAULT_NEARBY_CATEGORY, radius)
