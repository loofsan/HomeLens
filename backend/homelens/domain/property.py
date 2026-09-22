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
