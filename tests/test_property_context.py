"""Provider context stays optional, attributed, and isolated from sale search."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
from flask import Flask
from homelens import create_app
from homelens.adapters.google_maps import (
    PLACES_URL,
    SOLAR_URL,
    STREET_VIEW_URL,
    GoogleContextProvider,
    UrlLibGoogleTransport,
)
from homelens.data.property_catalog import write_catalog
from homelens.data.property_repository import SqlitePropertyRepository
from homelens.domain.property import HistoricalSale
from homelens.domain.property_context import ProviderRequestError
from homelens.services.property_context import PropertyContextService

SALE_ID = "sale_" + "a" * 32


def _app(tmp_path: Path, key: str | None = None) -> Flask:
    database = tmp_path / "sales.sqlite3"
    write_catalog(
        database,
        [
            HistoricalSale(
                id=SALE_ID,
                sale_date=date(2024, 6, 1),
                sold_price_usd=350000,
                beds=3,
                baths=2,
                square_feet=1200,
                year_built=1990,
                property_type="Townhouse",
                address="1 Main St",
                city="Durham",
                state="NC",
                zip="27703",
                latitude=36.0,
                longitude=-79.0,
                source_url=None,
            )
        ],
        {
            "imported_rows": 1,
            "source_identity": {"sha256": "a" * 64},
            "boundary_source_identity": {"sha256": "b" * 64},
            "sale_date_range": ["2024-06-01", "2024-06-01"],
        },
    )
    return create_app(
        {
            "TESTING": True,
            "PROPERTY_CATALOG_PATH": database,
            "GOOGLE_MAPS_API_KEY": key,
        }
    )


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.fail: str | None = None

    def json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (method, url, {"params": params, "body": body, "headers": headers})
        )
        if self.fail == url:
            raise ProviderRequestError("provider_timeout")
        if url == PLACES_URL:
            return {
                "places": [
                    {
                        "displayName": {"text": "Duke Park"},
                        "primaryType": "park",
                        "location": {"latitude": 36.004, "longitude": -79.0},
                        "googleMapsUri": "https://maps.google.com/?cid=123",
                        "attributions": [
                            {
                                "provider": "City of Durham",
                                "providerUri": "https://www.durhamnc.gov/",
                            }
                        ],
                    }
                ]
            }
        if url == f"{STREET_VIEW_URL}/metadata":
            return {
                "status": "OK",
                "location": {"latitude": 36.0002, "longitude": -79.0},
                "date": "2023-08",
                "copyright": "Google",
            }
        if url == SOLAR_URL:
            return {
                "center": {"latitude": 36.0001, "longitude": -79.0},
                "postalCode": "27703",
                "imageryDate": {"year": 2022, "month": 5, "day": 7},
                "imageryQuality": "HIGH",
                "solarPotential": {
                    "maxArrayPanelsCount": 10,
                    "panelCapacityWatts": 400,
                },
            }
        raise AssertionError(url)

    def image(self, url: str, *, params: dict[str, str]) -> tuple[bytes, str]:
        self.calls.append(("GET", url, {"params": params}))
        return b"\xff\xd8\xff\xd9", "image/jpeg"


def _with_transport(app: Flask, transport: FakeTransport) -> None:
    repository = SqlitePropertyRepository(Path(app.config["PROPERTY_CATALOG_PATH"]))
    app.extensions["property_context"] = PropertyContextService(
        repository, GoogleContextProvider("secret-key", transport)
    )


def test_missing_key_is_explicit_and_makes_no_provider_calls(tmp_path: Path) -> None:
    client = _app(tmp_path).test_client()
    response = client.get(f"/api/properties/{SALE_ID}/context")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.get_json()
    assert payload["property_id"] == SALE_ID
    assert payload["coordinate_source"] == "historical_sale_catalog"
    for name in ("nearby_places", "street_view", "solar"):
        assert payload[name]["status"] == "unavailable"
        assert payload[name]["reason"] == "not_configured"
        assert payload[name]["data"] is None
    assert client.get(f"/api/properties/{SALE_ID}/street-view/image").status_code == 404
    assert client.get("/api/properties").status_code == 200


def test_google_adapters_use_bounded_requests_and_keep_key_server_side(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    transport = FakeTransport()
    _with_transport(app, transport)
    client = app.test_client()
    response = client.get(f"/api/properties/{SALE_ID}/context")
    assert response.status_code == 200
    assert b"secret-key" not in response.data
    payload = response.get_json()
    nearby = payload["nearby_places"]
    assert nearby["status"] == "available"
    assert nearby["coverage"]["radius_m"] == 1500
    assert nearby["data"]["places"][0]["distance_m"] < 500
    assert (
        nearby["data"]["places"][0]["attributions"][0]["provider"] == "City of Durham"
    )
    street = payload["street_view"]
    assert street["status"] == "available"
    assert street["coverage"]["radius_m"] == 50
    assert street["data"]["captured"] == "2023-08"
    solar = payload["solar"]
    assert solar["status"] == "available"
    assert solar["coverage"]["property_match_verified"] is False
    assert solar["data"]["max_array_capacity_kw"] == 4.0
    assert solar["data"]["imagery_date"] == "2022-05-07"

    places_call = transport.calls[0]
    assert places_call[0:2] == ("POST", PLACES_URL)
    assert places_call[2]["body"]["locationRestriction"]["circle"]["radius"] == 1500
    assert places_call[2]["body"]["rankPreference"] == "DISTANCE"
    assert places_call[2]["headers"]["X-Goog-Api-Key"] == "secret-key"
    assert "places.attributions" in places_call[2]["headers"]["X-Goog-FieldMask"]
    assert transport.calls[1][2]["params"]["radius"] == "50"
    assert transport.calls[2][2]["params"]["requiredQuality"] == "BASE"

    image = client.get(f"/api/properties/{SALE_ID}/street-view/image")
    assert image.status_code == 200
    assert image.mimetype == "image/jpeg"
    assert image.data == b"\xff\xd8\xff\xd9"
    assert image.headers["Cache-Control"] == "no-store"
    assert transport.calls[3][1] == STREET_VIEW_URL
    assert transport.calls[3][2]["params"]["return_error_code"] == "true"


def test_provider_failure_is_partial_and_does_not_break_sale_detail(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    transport = FakeTransport()
    transport.fail = PLACES_URL
    _with_transport(app, transport)
    client = app.test_client()
    payload = client.get(f"/api/properties/{SALE_ID}/context").get_json()
    assert payload["nearby_places"]["status"] == "error"
    assert payload["nearby_places"]["reason"] == "provider_timeout"
    assert payload["street_view"]["status"] == "available"
    assert payload["solar"]["status"] == "available"
    assert client.get(f"/api/properties/{SALE_ID}").status_code == 200


def test_missing_sale_and_catalog_are_explicit(tmp_path: Path) -> None:
    client = _app(tmp_path).test_client()
    assert client.get("/api/properties/unknown/context").status_code == 404
    assert client.get("/api/properties/unknown/street-view/image").status_code == 404
    missing_catalog = create_app(
        {"TESTING": True, "PROPERTY_CATALOG_PATH": tmp_path / "missing.sqlite3"}
    ).test_client()
    response = missing_catalog.get(f"/api/properties/{SALE_ID}/context")
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "catalog_unavailable"


def test_transport_sanitizes_timeout_and_no_coverage() -> None:
    transport = UrlLibGoogleTransport(timeout_seconds=0.25)
    with patch(
        "homelens.adapters.google_maps.urlopen", side_effect=TimeoutError("secret-key")
    ):
        with pytest.raises(ProviderRequestError) as timeout:
            transport.json("GET", SOLAR_URL)
    assert timeout.value.reason == "provider_timeout"
    assert "secret-key" not in str(timeout.value)

    with patch(
        "homelens.adapters.google_maps.urlopen",
        side_effect=HTTPError(SOLAR_URL, 404, "not found", None, None),
    ):
        with pytest.raises(ProviderRequestError) as not_found:
            transport.json("GET", SOLAR_URL)
    assert not_found.value.reason == "not_covered"
