"""Validated HTTP access to historical property sales."""

from __future__ import annotations

import math
import re
from dataclasses import asdict
from typing import Any, cast

from flask import Blueprint, Response, current_app, jsonify, request

from homelens.data.property_repository import CatalogUnavailableError
from homelens.domain.property import HistoricalSale, MapBounds, PropertyQuery
from homelens.domain.property_summary import historical_sale_summary
from homelens.services.property_search import PropertySearchService

properties_bp = Blueprint("properties", __name__)
QUERY_FIELDS = frozenset(
    {
        "min_price",
        "max_price",
        "min_beds",
        "min_baths",
        "zip",
        "south",
        "west",
        "north",
        "east",
        "page",
        "page_size",
    }
)
BOUND_FIELDS = frozenset({"south", "west", "north", "east"})


class QueryError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def _number(field: str, minimum: float, maximum: float | None = None) -> float | None:
    raw = request.args.get(field)
    if raw is None:
        return None
    try:
        number = float(raw)
    except ValueError as exc:
        raise QueryError(field, "must be a number") from exc
    if (
        not math.isfinite(number)
        or number < minimum
        or (maximum is not None and number > maximum)
    ):
        raise QueryError(field, "is outside the allowed range")
    return number


def _integer(field: str, default: int, maximum: int) -> int:
    raw = request.args.get(field)
    if raw is None:
        return default
    if not re.fullmatch(r"[1-9]\d*", raw):
        raise QueryError(field, "must be a positive integer")
    number = int(raw)
    if number > maximum:
        raise QueryError(field, f"must not exceed {maximum}")
    return number


def _query() -> PropertyQuery:
    for field in request.args:
        if field not in QUERY_FIELDS:
            raise QueryError(field, "unknown filter")
        if len(request.args.getlist(field)) != 1:
            raise QueryError(field, "must appear once")
    zip_code = request.args.get("zip")
    if zip_code is not None and not re.fullmatch(r"\d{5}", zip_code):
        raise QueryError("zip", "must be five digits")
    supplied_bounds = BOUND_FIELDS.intersection(request.args.keys())
    if supplied_bounds and supplied_bounds != BOUND_FIELDS:
        raise QueryError("bounds", "south, west, north, and east are required together")
    bounds = None
    if supplied_bounds:
        south = _number("south", -90, 90)
        west = _number("west", -180, 180)
        north = _number("north", -90, 90)
        east = _number("east", -180, 180)
        assert south is not None and west is not None
        assert north is not None and east is not None
        if south >= north or west >= east:
            raise QueryError("bounds", "south must precede north and west precede east")
        bounds = MapBounds(south=south, west=west, north=north, east=east)

    min_price = _number("min_price", 0)
    max_price = _number("max_price", 0)
    if min_price is not None and max_price is not None and min_price > max_price:
        raise QueryError("max_price", "must be at least min_price")
    return PropertyQuery(
        min_price=min_price,
        max_price=max_price,
        min_beds=_number("min_beds", 0),
        min_baths=_number("min_baths", 0),
        zip=zip_code,
        bounds=bounds,
        page=_integer("page", 1, 100_000),
        page_size=_integer("page_size", 20, 100),
    )


def _service() -> PropertySearchService:
    return cast(PropertySearchService, current_app.extensions["property_search"])


def _record(record: HistoricalSale) -> dict[str, Any]:
    payload = asdict(record)
    payload["sale_date"] = record.sale_date.isoformat()
    return payload


@properties_bp.errorhandler(CatalogUnavailableError)
def _unavailable(_error: CatalogUnavailableError) -> tuple[Response, int]:
    return (
        jsonify(
            {
                "error": {
                    "code": "catalog_unavailable",
                    "message": (
                        "Historical sales are unavailable. "
                        "Run the offline catalog import."
                    ),
                }
            }
        ),
        503,
    )


@properties_bp.get("/api/properties")
def search_properties() -> Response | tuple[Response, int]:
    try:
        query = _query()
    except QueryError as exc:
        return (
            jsonify(
                {
                    "error": {
                        "code": "invalid_query",
                        "field": exc.field,
                        "message": str(exc),
                    }
                }
            ),
            400,
        )
    page = _service().search(query)
    return jsonify(
        {
            "items": [_record(record) for record in page.items],
            "total": page.total,
            "page": page.page,
            "page_size": page.page_size,
            "source": asdict(page.source),
        }
    )


@properties_bp.get("/api/properties/<property_id>")
def get_property(property_id: str) -> Response | tuple[Response, int]:
    record, source = _service().get(property_id)
    if record is None:
        return (
            jsonify(
                {
                    "error": {
                        "code": "property_not_found",
                        "message": "Historical sale was not found.",
                    }
                }
            ),
            404,
        )
    return jsonify(
        {
            "property": _record(record),
            "source": asdict(source),
            "description": historical_sale_summary(record),
        }
    )
