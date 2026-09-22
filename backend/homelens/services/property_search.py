"""Historical-property search use case."""

from __future__ import annotations

from typing import Protocol

from homelens.domain.property import (
    CatalogSource,
    HistoricalSale,
    PropertyPage,
    PropertyQuery,
)


class PropertyRepository(Protocol):
    def search(self, query: PropertyQuery) -> PropertyPage: ...

    def get(self, property_id: str) -> tuple[HistoricalSale | None, CatalogSource]: ...


class PropertySearchService:
    def __init__(self, repository: PropertyRepository) -> None:
        self._repository = repository

    def search(self, query: PropertyQuery) -> PropertyPage:
        if (
            query.min_price is not None
            and query.max_price is not None
            and query.min_price > query.max_price
        ):
            raise ValueError("min_price must not exceed max_price")
        return self._repository.search(query)

    def get(self, property_id: str) -> tuple[HistoricalSale | None, CatalogSource]:
        return self._repository.get(property_id)
