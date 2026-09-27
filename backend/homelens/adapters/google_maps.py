"""Bounded, server-side Google Maps Platform requests for nearby context."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import date
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from homelens.domain.property import HistoricalSale
from homelens.domain.property_context import (
    ContextSection,
    NearbyQuery,
    ProviderRequestError,
    section,
)

PLACES_URL = "https://places.googleapis.com/v1/places:searchNearby"
STREET_VIEW_URL = "https://maps.googleapis.com/maps/api/streetview"
SOLAR_URL = "https://solar.googleapis.com/v1/buildingInsights:findClosest"
STREET_VIEW_RADIUS_M = 50
PANO_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
PLACES_MAX_RESULTS = 10
PLACES_FIELDS = (
    "places.displayName,places.location,places.primaryType,"
    "places.googleMapsUri,places.attributions"
)


class GoogleTransport(Protocol):
    def json(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]: ...

    def image(self, url: str, *, params: Mapping[str, str]) -> tuple[bytes, str]: ...


class UrlLibGoogleTransport:
    def __init__(self, timeout_seconds: float = 3.0) -> None:
        self.timeout_seconds = timeout_seconds

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[bytes, str]:
        if params:
            url = f"{url}?{urlencode(params)}"
        request_headers = {"Accept": "application/json", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                content = response.read(2_000_001)
                if len(content) > 2_000_000:
                    raise ProviderRequestError("invalid_response")
                return content, response.headers.get_content_type()
        except HTTPError as exc:
            if exc.code == 404:
                raise ProviderRequestError("not_covered") from None
            if exc.code in (401, 403):
                raise ProviderRequestError("provider_denied") from None
            if exc.code == 429:
                raise ProviderRequestError("provider_limit") from None
            raise ProviderRequestError("provider_error") from None
        except (TimeoutError, URLError):
            raise ProviderRequestError("provider_timeout") from None

    def json(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        content, _ = self._request(
            method, url, params=params, body=body, headers=headers
        )
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderRequestError("invalid_response") from None
        if not isinstance(payload, dict):
            raise ProviderRequestError("invalid_response")
        return cast(dict[str, Any], payload)

    def image(self, url: str, *, params: Mapping[str, str]) -> tuple[bytes, str]:
        content, content_type = self._request("GET", url, params=params)
        if content_type not in ("image/jpeg", "image/png"):
            raise ProviderRequestError("invalid_response")
        return content, content_type


def _distance_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> int:
    lat1, lat2 = math.radians(lat_a), math.radians(lat_b)
    dlat = lat2 - lat1
    dlon = math.radians(lon_b - lon_a)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return round(6_371_000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _bearing_deg(
    lat_a: float, lon_a: float, lat_b: float, lon_b: float
) -> float | None:
    """Initial great-circle bearing from A to B, clockwise from true north."""
    if abs(lat_a - lat_b) < 1e-7 and abs(lon_a - lon_b) < 1e-7:
        return None
    lat1, lat2 = math.radians(lat_a), math.radians(lat_b)
    dlon = math.radians(lon_b - lon_a)
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(
        dlon
    )
    return round(math.degrees(math.atan2(y, x)) % 360, 1) % 360


def _coordinates(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    latitude, longitude = value.get("latitude"), value.get("longitude")
    if not isinstance(latitude, (int, float)) or not isinstance(
        longitude, (int, float)
    ):
        return None
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return float(latitude), float(longitude)


def _https_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    return value if parsed.scheme == "https" and parsed.netloc else None


def _date(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    try:
        return date(value["year"], value["month"], value["day"]).isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _money_usd(value: Any) -> float | None:
    """Convert a google.type.Money value to dollars; other currencies are dropped."""
    if not isinstance(value, dict) or value.get("currencyCode", "USD") != "USD":
        return None
    units = value.get("units", "0")
    nanos = value.get("nanos", 0)
    try:
        amount = int(units) + int(nanos) / 1e9
    except (TypeError, ValueError):
        return None
    return round(amount, 2) if math.isfinite(amount) else None


def _solar_financials(potential: dict[str, Any]) -> list[dict[str, Any]]:
    """Cash-purchase scenarios from the Solar API, one per modeled monthly bill."""
    configs = potential.get("solarPanelConfigs")
    configs = configs if isinstance(configs, list) else []
    options: list[dict[str, Any]] = []
    for raw in potential.get("financialAnalyses", []):
        if not isinstance(raw, dict):
            continue
        index = raw.get("panelConfigIndex")
        details = raw.get("financialDetails")
        cash = raw.get("cashPurchaseSavings")
        bill = _money_usd(raw.get("monthlyBill"))
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < len(configs)
            or not isinstance(configs[index], dict)
            or not isinstance(details, dict)
            or not isinstance(cash, dict)
            or bill is None
        ):
            continue
        savings = cash.get("savings")
        savings = savings if isinstance(savings, dict) else {}
        panels = configs[index].get("panelsCount")
        payback = _number(cash.get("paybackYears"))
        option = {
            "monthly_bill_usd": bill,
            "is_default_bill": raw.get("defaultBill") is True,
            "panels_count": panels
            if isinstance(panels, int) and not isinstance(panels, bool)
            else None,
            "yearly_energy_dc_kwh": _number(configs[index].get("yearlyEnergyDcKwh")),
            "solar_percentage": _number(details.get("solarPercentage")),
            "net_metering_allowed": details.get("netMeteringAllowed")
            if isinstance(details.get("netMeteringAllowed"), bool)
            else None,
            "lifetime_cost_without_solar_usd": _money_usd(
                details.get("costOfElectricityWithoutSolar")
            ),
            "lifetime_remaining_bill_usd": _money_usd(
                details.get("remainingLifetimeUtilityBill")
            ),
            "upfront_cost_usd": _money_usd(cash.get("upfrontCost")),
            "incentives_usd": _money_usd(cash.get("rebateValue")),
            "out_of_pocket_cost_usd": _money_usd(cash.get("outOfPocketCost")),
            "payback_years": payback if payback is not None and payback >= 0 else None,
            "savings_year1_usd": _money_usd(savings.get("savingsYear1")),
            "savings_lifetime_usd": _money_usd(savings.get("savingsLifetime")),
            "financially_viable": savings.get("financiallyViable")
            if isinstance(savings.get("financiallyViable"), bool)
            else None,
        }
        if option["upfront_cost_usd"] is None:
            continue
        options.append(option)
    options.sort(key=lambda option: option["monthly_bill_usd"])
    return options


class GoogleContextProvider:
    def __init__(
        self, api_key: str | None, transport: GoogleTransport | None = None
    ) -> None:
        self._api_key = api_key or None
        self._transport = transport or UrlLibGoogleTransport()

    def nearby(
        self, sale: HistoricalSale, query: NearbyQuery | None = None
    ) -> ContextSection:
        query = query or NearbyQuery()
        source = "Google Maps Places API (New)"
        coverage = {
            "category": query.category,
            "radius_m": query.radius_m,
            "types": list(query.types),
            "ranking": "distance",
            "distance_kind": "straight_line",
        }
        if not self._api_key:
            return section("unavailable", source, coverage, reason="not_configured")
        try:
            payload = self._transport.json(
                "POST",
                PLACES_URL,
                headers={
                    "X-Goog-Api-Key": self._api_key,
                    "X-Goog-FieldMask": PLACES_FIELDS,
                },
                body={
                    "includedTypes": list(query.types),
                    "maxResultCount": PLACES_MAX_RESULTS,
                    "rankPreference": "DISTANCE",
                    "locationRestriction": {
                        "circle": {
                            "center": {
                                "latitude": sale.latitude,
                                "longitude": sale.longitude,
                            },
                            "radius": query.radius_m,
                        }
                    },
                },
            )
        except ProviderRequestError as exc:
            return section("error", source, coverage, reason=exc.reason)

        places: list[dict[str, Any]] = []
        for raw in payload.get("places", []):
            if not isinstance(raw, dict):
                continue
            name = raw.get("displayName")
            name = name.get("text") if isinstance(name, dict) else None
            coordinates = _coordinates(raw.get("location"))
            if not isinstance(name, str) or not name or not coordinates:
                continue
            attributions = []
            for attribution in raw.get("attributions", []):
                if isinstance(attribution, dict) and isinstance(
                    attribution.get("provider"), str
                ):
                    attributions.append(
                        {
                            "provider": attribution["provider"],
                            "url": _https_url(attribution.get("providerUri")),
                        }
                    )
            places.append(
                {
                    "name": name,
                    "type": raw.get("primaryType")
                    if isinstance(raw.get("primaryType"), str)
                    else None,
                    "distance_m": _distance_m(
                        sale.latitude, sale.longitude, *coordinates
                    ),
                    "maps_url": _https_url(raw.get("googleMapsUri")),
                    "attributions": attributions,
                }
            )
        if not places:
            return section("unavailable", source, coverage, reason="no_results")
        return section("available", source, coverage, data={"places": places})

    def _panorama(self, sale: HistoricalSale) -> dict[str, Any]:
        """Find the nearest outdoor panorama and the heading toward the sale."""
        assert self._api_key
        payload = self._transport.json(
            "GET",
            f"{STREET_VIEW_URL}/metadata",
            params={
                "location": f"{sale.latitude},{sale.longitude}",
                "radius": str(STREET_VIEW_RADIUS_M),
                "source": "outdoor",
                "key": self._api_key,
            },
        )
        status = payload.get("status")
        if status in ("ZERO_RESULTS", "NOT_FOUND"):
            raise ProviderRequestError("not_covered")
        if status != "OK":
            raise ProviderRequestError("provider_error")
        coordinates = _coordinates(payload.get("location"))
        if not coordinates:
            raise ProviderRequestError("invalid_response")
        distance = _distance_m(sale.latitude, sale.longitude, *coordinates)
        if distance > STREET_VIEW_RADIUS_M:
            raise ProviderRequestError("not_covered")
        pano_id = payload.get("pano_id")
        return {
            "pano_id": pano_id
            if isinstance(pano_id, str) and PANO_ID_PATTERN.fullmatch(pano_id)
            else None,
            "distance_m": distance,
            "heading_deg": _bearing_deg(*coordinates, sale.latitude, sale.longitude),
            "captured": payload.get("date")
            if isinstance(payload.get("date"), str)
            else None,
            "copyright": payload.get("copyright")
            if isinstance(payload.get("copyright"), str)
            else None,
        }

    def street_view(self, sale: HistoricalSale) -> ContextSection:
        source = "Google Maps Street View Static API"
        coverage = {"radius_m": STREET_VIEW_RADIUS_M, "source": "outdoor"}
        if not self._api_key:
            return section("unavailable", source, coverage, reason="not_configured")
        try:
            panorama = self._panorama(sale)
        except ProviderRequestError as exc:
            if exc.reason == "not_covered":
                return section("unavailable", source, coverage, reason=exc.reason)
            return section("error", source, coverage, reason=exc.reason)
        heading = panorama["heading_deg"]
        maps_url = (
            "https://www.google.com/maps/@?api=1&map_action=pano&"
            f"viewpoint={sale.latitude},{sale.longitude}"
        )
        if panorama["pano_id"]:
            maps_url += f"&pano={panorama['pano_id']}"
        if heading is not None:
            maps_url += f"&heading={heading}"
        return section(
            "available",
            source,
            coverage,
            data={
                "captured": panorama["captured"],
                "copyright": panorama["copyright"],
                "distance_m": panorama["distance_m"],
                "heading_deg": heading,
                "image_url": f"/api/properties/{sale.id}/street-view/image",
                "maps_url": maps_url,
            },
        )

    def street_view_image(self, sale: HistoricalSale) -> tuple[bytes, str]:
        if not self._api_key:
            raise ProviderRequestError("not_configured")
        panorama = self._panorama(sale)
        params = {"size": "600x320", "return_error_code": "true"}
        if panorama["pano_id"]:
            params["pano"] = panorama["pano_id"]
        else:
            params.update(
                {
                    "location": f"{sale.latitude},{sale.longitude}",
                    "radius": str(STREET_VIEW_RADIUS_M),
                    "source": "outdoor",
                }
            )
        if panorama["heading_deg"] is not None:
            params["heading"] = str(panorama["heading_deg"])
        params["key"] = self._api_key
        return self._transport.image(STREET_VIEW_URL, params=params)

    def solar(self, sale: HistoricalSale) -> ContextSection:
        source = "Google Maps Solar API"
        coverage = {
            "method": "closest_building",
            "approx_max_distance_m": 50,
            "property_match_verified": False,
        }
        if not self._api_key:
            return section("unavailable", source, coverage, reason="not_configured")
        try:
            payload = self._transport.json(
                "GET",
                SOLAR_URL,
                params={
                    "location.latitude": str(sale.latitude),
                    "location.longitude": str(sale.longitude),
                    "requiredQuality": "BASE",
                    "key": self._api_key,
                },
            )
        except ProviderRequestError as exc:
            if exc.reason == "not_covered":
                return section("unavailable", source, coverage, reason=exc.reason)
            return section("error", source, coverage, reason=exc.reason)
        coordinates = _coordinates(payload.get("center"))
        potential = payload.get("solarPotential")
        if not coordinates or not isinstance(potential, dict):
            return section("error", source, coverage, reason="invalid_response")
        count = potential.get("maxArrayPanelsCount")
        watts = potential.get("panelCapacityWatts")
        if (
            not isinstance(count, int)
            or count < 0
            or not isinstance(watts, (int, float))
            or not math.isfinite(watts)
            or watts <= 0
        ):
            return section("error", source, coverage, reason="invalid_response")
        return section(
            "available",
            source,
            coverage,
            data={
                "building_distance_m": _distance_m(
                    sale.latitude, sale.longitude, *coordinates
                ),
                "imagery_date": _date(payload.get("imageryDate")),
                "imagery_quality": payload.get("imageryQuality")
                if payload.get("imageryQuality") in ("HIGH", "MEDIUM", "BASE")
                else None,
                "max_array_panels_count": count,
                "panel_capacity_watts": watts,
                "max_array_capacity_kw": round(count * watts / 1000, 1),
                "postal_code_matches": (
                    payload["postalCode"] == sale.zip
                    if isinstance(payload.get("postalCode"), str)
                    else None
                ),
                "max_array_area_m2": _number(potential.get("maxArrayAreaMeters2")),
                "max_sunshine_hours_per_year": _number(
                    potential.get("maxSunshineHoursPerYear")
                ),
                "carbon_offset_kg_per_mwh": _number(
                    potential.get("carbonOffsetFactorKgPerMwh")
                ),
                "panel_lifetime_years": _number(potential.get("panelLifetimeYears")),
                "financial_scenarios": _solar_financials(potential),
            },
        )
