"""Serve prepared ACS ZCTA profiles for a sale's recorded ZIP code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homelens.services.property_search import PropertyRepository

SOURCE = "U.S. Census Bureau American Community Survey"
ZCTA_NOTE = (
    "ZIP Code Tabulation Areas approximate USPS ZIP code delivery areas and may "
    "not match the recorded ZIP exactly."
)


class DemographicsUnavailableError(Exception):
    """The prepared profile file is missing or has an unexpected shape."""


class DemographicsService:
    def __init__(self, repository: PropertyRepository, profiles_path: Path) -> None:
        self._repository = repository
        self._report: dict[str, Any] | None = None
        try:
            report = json.loads(profiles_path.read_text(encoding="utf-8"))
            if (
                not isinstance(report, dict)
                or report.get("geography_level") != "zcta"
                or not isinstance(report.get("profiles"), dict)
                or not isinstance(report.get("period"), str)
            ):
                raise ValueError("unexpected profile file")
            self._report = report
        except (OSError, ValueError):
            self._report = None

    def get(self, property_id: str) -> dict[str, Any] | None:
        sale, source = self._repository.get(property_id)
        if sale is None:
            return None
        base: dict[str, Any] = {
            "property_id": sale.id,
            "source": SOURCE,
            "geography": {"kind": "zcta", "id": sale.zip, "note": ZCTA_NOTE},
        }
        if source.synthetic:
            return {**base, "status": "unavailable", "reason": "synthetic_demo"}
        if self._report is None:
            raise DemographicsUnavailableError
        profile = self._report["profiles"].get(sale.zip)
        details = {
            "dataset": self._report.get("dataset"),
            "period": self._report["period"],
        }
        if not isinstance(profile, dict):
            return {
                **base,
                **details,
                "status": "unavailable",
                "reason": "zcta_not_prepared",
            }
        return {
            **base,
            **details,
            "status": "available",
            "reason": None,
            "metrics": profile,
        }
