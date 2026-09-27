"""Move a recorded sale price along its ZIP's value index; no forecast."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homelens.services.property_search import PropertyRepository

SOURCE = "Supplied ZIP home value index (Zillow Research layout)"
METHOD_NOTE = (
    "Index adjustment multiplies the recorded sale price by the ZIP index change "
    "since the sale month. It assumes this home's value moved with its ZIP's "
    "typical home value and is not an appraisal or current market value."
)


class ValueTrendUnavailableError(Exception):
    """The prepared index file is missing or has an unexpected shape."""


class ValueTrendService:
    def __init__(self, repository: PropertyRepository, index_path: Path) -> None:
        self._repository = repository
        self._index: dict[str, Any] | None = None
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            months = index.get("months") if isinstance(index, dict) else None
            zips = index.get("zips") if isinstance(index, dict) else None
            if (
                not isinstance(months, list)
                or not months
                or not isinstance(zips, dict)
                or any(len(values) != len(months) for values in zips.values())
            ):
                raise ValueError("unexpected index file")
            self._index = index
        except (OSError, ValueError, AttributeError, TypeError):
            self._index = None

    def get(self, property_id: str) -> dict[str, Any] | None:
        sale, source = self._repository.get(property_id)
        if sale is None:
            return None
        base: dict[str, Any] = {"property_id": sale.id, "zip": sale.zip}
        if source.synthetic:
            return {**base, "status": "unavailable", "reason": "synthetic_demo"}
        if self._index is None:
            raise ValueTrendUnavailableError
        index = self._index
        months: list[str] = index["months"]
        details = {
            "source": SOURCE,
            "series_label": index.get("series_label"),
            "variant_confirmed": bool(index.get("variant_confirmed")),
            "method_note": METHOD_NOTE,
            "forecast": None,
            "forecast_note": index.get("forecast_note"),
        }
        values = index["zips"].get(sale.zip)
        if values is None:
            return {
                **base,
                **details,
                "status": "unavailable",
                "reason": "zip_not_in_index",
            }
        sale_month = sale.sale_date.strftime("%Y-%m")
        if sale_month not in months:
            reason = (
                "sale_after_index" if sale_month > months[-1] else "sale_before_index"
            )
            return {**base, **details, "status": "unavailable", "reason": reason}
        start = months.index(sale_month)
        base_value = values[start]
        if base_value is None:
            return {
                **base,
                **details,
                "status": "unavailable",
                "reason": "index_missing",
            }
        points = [
            {
                "month": month,
                "index_value": value,
                "adjusted_value_usd": round(sale.sold_price_usd * value / base_value),
            }
            for month, value in zip(months[start:], values[start:], strict=True)
            if value is not None
        ]
        latest = points[-1]
        return {
            **base,
            **details,
            "status": "available",
            "reason": None,
            "sale_month": sale_month,
            "sale_price_usd": sale.sold_price_usd,
            "latest_month": latest["month"],
            "latest_adjusted_value_usd": latest["adjusted_value_usd"],
            "index_change_pct": round(
                (latest["index_value"] / base_value - 1) * 100, 1
            ),
            "points": points,
        }
