"""Beat-level reported offense counts for the map layer."""

from __future__ import annotations

import re
from typing import cast

from flask import Blueprint, Response, current_app, jsonify, request

from homelens.services.crime_map import (
    CrimeMapService,
    CrimeMapUnavailableError,
    CrimeQueryError,
)

crime_bp = Blueprint("crime", __name__)


@crime_bp.get("/api/crime/beats")
def crime_beats() -> Response | tuple[Response, int]:
    service = cast(CrimeMapService, current_app.extensions["crime_map"])
    raw_year = request.args.get("year")
    try:
        for field in request.args:
            if field not in ("year", "category"):
                raise CrimeQueryError(field, "unknown parameter")
        if raw_year is not None and not re.fullmatch(r"\d{4}", raw_year):
            raise CrimeQueryError("year", "must be a four-digit year")
        result = service.get(
            int(raw_year) if raw_year is not None else None,
            request.args.get("category", "violent"),
        )
    except CrimeQueryError as exc:
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
    except CrimeMapUnavailableError:
        return (
            jsonify(
                {
                    "error": {
                        "code": "crime_map_unavailable",
                        "message": (
                            "The crime map is not prepared. "
                            "Run the offline police-beat aggregation."
                        ),
                    }
                }
            ),
            503,
        )
    return jsonify(result)
