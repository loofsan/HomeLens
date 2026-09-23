"""Historical property-sale contract, distinct from active listings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

PropertyType = Literal[
    "Single Family Residential",
    "Townhouse",
    "Condo/Co-op",
]
CATALOG_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class HistoricalSale:
    id: str
    sale_date: date
    sold_price_usd: float
    beds: float
    baths: float
    square_feet: float
    year_built: int
    property_type: PropertyType
    address: str
    city: str
    state: Literal["NC"]
    zip: str
    latitude: float
    longitude: float
    source_url: str | None
    record_kind: Literal["historical_sale"] = "historical_sale"


@dataclass(frozen=True, slots=True)
class MapBounds:
    south: float
    west: float
    north: float
    east: float


@dataclass(frozen=True, slots=True)
class PropertyQuery:
    min_price: float | None = None
    max_price: float | None = None
    min_beds: float | None = None
    min_baths: float | None = None
    zip: str | None = None
    bounds: MapBounds | None = None
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True, slots=True)
class CatalogSource:
    name: str
    latest_sale_date: str | None
    source_sha256: str
    boundary_sha256: str
    record_kind: Literal["historical_sale"] = "historical_sale"
    active_listings: Literal[False] = False


@dataclass(frozen=True, slots=True)
class PropertyPage:
    items: list[HistoricalSale]
    total: int
    page: int
    page_size: int
    source: CatalogSource
