"""Bounded, server-side Google Maps Platform requests for nearby context."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import date
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from homelens.domain.property import HistoricalSale
from homelens.domain.property_context import (
    ContextSection,
    ProviderRequestError,
    section,
)

PLACES_URL = "https://places.googleapis.com/v1/places:searchNearby"
STREET_VIEW_URL = "https://maps.googleapis.com/maps/api/streetview"
SOLAR_URL = "https://solar.googleapis.com/v1/buildingInsights:findClosest"
PLACES_RADIUS_M = 1500
STREET_VIEW_RADIUS_M = 50
PLACES_TYPES = ("supermarket", "park", "school", "pharmacy")
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


class GoogleContextProvider:
    def __init__(
        self, api_key: str | None, transport: GoogleTransport | None = None
    ) -> None:
        self._api_key = api_key or None
        self._transport = transport or UrlLibGoogleTransport()

    def nearby(self, sale: HistoricalSale) -> ContextSection:
        source = "Google Maps Places API (New)"
        coverage = {
            "radius_m": PLACES_RADIUS_M,
            "types": list(PLACES_TYPES),
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
                    "includedTypes": list(PLACES_TYPES),
                    "maxResultCount": 8,
                    "rankPreference": "DISTANCE",
                    "locationRestriction": {
                        "circle": {
                            "center": {
                                "latitude": sale.latitude,
                                "longitude": sale.longitude,
                            },
                            "radius": PLACES_RADIUS_M,
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

    def street_view(self, sale: HistoricalSale) -> ContextSection:
        source = "Google Maps Street View Static API"
        coverage = {"radius_m": STREET_VIEW_RADIUS_M, "source": "outdoor"}
        if not self._api_key:
            return section("unavailable", source, coverage, reason="not_configured")
        try:
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
        except ProviderRequestError as exc:
            return section("error", source, coverage, reason=exc.reason)
        status = payload.get("status")
        if status in ("ZERO_RESULTS", "NOT_FOUND"):
            return section("unavailable", source, coverage, reason="not_covered")
        if status != "OK":
            return section("error", source, coverage, reason="provider_error")
        coordinates = _coordinates(payload.get("location"))
        if not coordinates:
            return section("error", source, coverage, reason="invalid_response")
        distance = _distance_m(sale.latitude, sale.longitude, *coordinates)
        if distance > STREET_VIEW_RADIUS_M:
            return section("unavailable", source, coverage, reason="not_covered")
        return section(
            "available",
            source,
            coverage,
            data={
                "captured": payload.get("date")
                if isinstance(payload.get("date"), str)
                else None,
                "copyright": payload.get("copyright")
                if isinstance(payload.get("copyright"), str)
                else None,
                "distance_m": distance,
                "image_url": f"/api/properties/{sale.id}/street-view/image",
                "maps_url": (
                    "https://www.google.com/maps/@?api=1&map_action=pano&"
                    f"viewpoint={sale.latitude},{sale.longitude}"
                ),
            },
        )

    def street_view_image(self, sale: HistoricalSale) -> tuple[bytes, str]:
        if not self._api_key:
            raise ProviderRequestError("not_configured")
        return self._transport.image(
            STREET_VIEW_URL,
            params={
                "size": "600x320",
                "location": f"{sale.latitude},{sale.longitude}",
                "radius": str(STREET_VIEW_RADIUS_M),
                "source": "outdoor",
                "return_error_code": "true",
                "key": self._api_key,
            },
        )

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
            },
        )
