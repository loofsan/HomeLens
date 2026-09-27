"""Serve prepared beat-level offense counts for one year and category."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATEGORIES = ("violent", "property")


class CrimeMapUnavailableError(Exception):
    """The prepared beat file is missing or has an unexpected shape."""


class CrimeQueryError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class CrimeMapService:
    def __init__(self, path: Path) -> None:
        self._document: dict[str, Any] | None = None
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            metadata = document.get("metadata") if isinstance(document, dict) else None
            if (
                not isinstance(metadata, dict)
                or document.get("type") != "FeatureCollection"
                or not isinstance(document.get("features"), list)
                or not isinstance(metadata.get("years"), list)
                or not metadata["years"]
                or set(metadata.get("categories", {})) != set(CATEGORIES)
            ):
                raise ValueError("unexpected crime map file")
            self._document = document
        except (OSError, ValueError, AttributeError):
            self._document = None

    def _years(self) -> list[dict[str, Any]]:
        if self._document is None:
            raise CrimeMapUnavailableError
        return list(self._document["metadata"]["years"])

    def default_year(self) -> int:
        years = self._years()
        complete = [item["year"] for item in years if item.get("complete")]
        return int(complete[-1] if complete else years[-1]["year"])

    def get(self, year: int | None, category: str) -> dict[str, Any]:
        years = self._years()
        assert self._document is not None
        if category not in CATEGORIES:
            raise CrimeQueryError("category", "must be violent or property")
        selected_year = self.default_year() if year is None else year
        coverage = next((item for item in years if item["year"] == selected_year), None)
        if coverage is None:
            raise CrimeQueryError(
                "year",
                "must be one of " + ", ".join(str(item["year"]) for item in years),
            )
        metadata = self._document["metadata"]
        features = []
        for feature in self._document["features"]:
            properties = feature["properties"]
            has_records = bool(properties.get("has_records", True))
            count = (
                properties["counts"].get(str(selected_year), {}).get(category)
                if has_records
                else None
            )
            area = properties.get("area_km2")
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "beat": properties["beat"],
                        "district": properties.get("district"),
                        "area_km2": area,
                        "count": count,
                        "per_km2": round(count / area, 1)
                        if count is not None and area
                        else None,
                    },
                    "geometry": feature["geometry"],
                }
            )
        return {
            "type": "FeatureCollection",
            "metadata": {
                "year": selected_year,
                "coverage": coverage,
                "years": years,
                "category": category,
                "category_label": metadata["categories"][category]["label"],
                "definition": metadata["categories"][category]["definition"],
                "record_unit": metadata.get("record_unit"),
                "source": "City of Durham Police Department crime table",
                "source_layer": metadata.get("source_layer"),
                "excluded_rows": {
                    key: metadata["rows"][key]
                    for key in ("missing_beat", "unmatched_beat", "invalid_report_date")
                    if key in metadata.get("rows", {})
                },
                "notes": metadata.get("notes", []),
            },
            "features": features,
        }
