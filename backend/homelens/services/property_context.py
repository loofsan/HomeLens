"""Resolve independent provider context for a catalog sale."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from homelens.domain.property import HistoricalSale
from homelens.domain.property_context import (
    ContextSection,
    ProviderRequestError,
    section,
)
from homelens.services.property_search import PropertyRepository


class ContextProvider(Protocol):
    def nearby(self, sale: HistoricalSale) -> ContextSection: ...

    def street_view(self, sale: HistoricalSale) -> ContextSection: ...

    def solar(self, sale: HistoricalSale) -> ContextSection: ...

    def street_view_image(self, sale: HistoricalSale) -> tuple[bytes, str]: ...


SOURCES = {
    "nearby_places": "Google Maps Places API (New)",
    "street_view": "Google Maps Street View Static API",
    "solar": "Google Maps Solar API",
}


class PropertyContextService:
    def __init__(
        self, repository: PropertyRepository, provider: ContextProvider
    ) -> None:
        self._repository = repository
        self._provider = provider

    def get(self, property_id: str) -> dict[str, Any] | None:
        sale, _ = self._repository.get(property_id)
        if sale is None:
            return None

        def run(
            name: str, operation: Callable[[HistoricalSale], ContextSection]
        ) -> ContextSection:
            try:
                return operation(sale)
            except Exception:
                return section("error", SOURCES[name], {}, reason="provider_error")

        return {
            "property_id": sale.id,
            "coordinate_source": "historical_sale_catalog",
            "nearby_places": run("nearby_places", self._provider.nearby),
            "street_view": run("street_view", self._provider.street_view),
            "solar": run("solar", self._provider.solar),
        }

    def street_view_image(self, property_id: str) -> tuple[bytes, str] | None:
        sale, _ = self._repository.get(property_id)
        if sale is None:
            return None
        try:
            return self._provider.street_view_image(sale)
        except ProviderRequestError:
            raise
        except Exception:
            raise ProviderRequestError("provider_error") from None
