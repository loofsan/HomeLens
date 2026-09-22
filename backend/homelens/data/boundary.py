"""Load the supplied Durham County polygon in WGS84 coordinates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry


def load_county_boundary(path: Path) -> BaseGeometry:
    if not path.is_file():
        raise FileNotFoundError(f"Missing boundary file: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid GeoJSON") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{path.name} must contain one polygon feature")

    geometry: Any = document
    if document.get("type") == "FeatureCollection":
        features = document.get("features")
        if not isinstance(features, list) or len(features) != 1:
            raise ValueError(f"{path.name} must contain exactly one county feature")
        geometry = (
            features[0].get("geometry") if isinstance(features[0], dict) else None
        )
    elif document.get("type") == "Feature":
        geometry = document.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError(f"{path.name} has no polygon geometry")

    try:
        boundary = shape(geometry)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path.name} has invalid polygon coordinates") from exc
    if (
        boundary.geom_type not in {"Polygon", "MultiPolygon"}
        or boundary.is_empty
        or not boundary.is_valid
    ):
        raise ValueError(f"{path.name} must contain one valid polygon boundary")
    min_lon, min_lat, max_lon, max_lat = boundary.bounds
    if not (-80 < min_lon < max_lon < -78 and 35 < min_lat < max_lat < 37):
        raise ValueError(f"{path.name} must use Durham-area WGS84 lon/lat coordinates")
    return boundary
