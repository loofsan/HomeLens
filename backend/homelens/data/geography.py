"""Compare historical sale coordinates with the Durham County boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import shapely
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from .inventory import (
    REDFIN_COLUMNS,
    _file_identity,
    _normalized_zips,
    _read_csv,
    _require_columns,
)
from .prepare import STUDY_ZIPS


def _load_boundary(path: Path) -> BaseGeometry:
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


def _counts_by_zip(zips: pd.Series[Any], mask: pd.Series[Any]) -> dict[str, int]:
    counts = zips.loc[mask].fillna("<missing>").value_counts().sort_index()
    return {str(zip_code): int(count) for zip_code, count in counts.items()}


def audit_geography(raw_dir: Path) -> dict[str, Any]:
    sales_path = raw_dir / "redfin_data.csv"
    boundary_path = raw_dir / "durham_county_boundary.geojson"
    boundary = _load_boundary(boundary_path)
    sales = _read_csv(sales_path, ("ZIP OR POSTAL CODE", "MLS#"))
    _require_columns(
        sales,
        sales_path,
        (*REDFIN_COLUMNS, "SALE TYPE", "LATITUDE", "LONGITUDE"),
    )

    unique = sales.drop_duplicates()
    sold_dates = pd.to_datetime(unique["SOLD DATE"], format="mixed", errors="coerce")
    prices = pd.to_numeric(unique["PRICE"], errors="coerce")
    historical_mask = (
        unique["SALE TYPE"].astype("string").str.strip().eq("PAST SALE").fillna(False)
        & sold_dates.notna()
        & prices.gt(0)
        & prices.lt(float("inf"))
    )
    historical = unique.loc[historical_mask]
    zips = _normalized_zips(historical["ZIP OR POSTAL CODE"])
    study_zip = zips.isin(STUDY_ZIPS)
    latitudes = pd.to_numeric(historical["LATITUDE"], errors="coerce")
    longitudes = pd.to_numeric(historical["LONGITUDE"], errors="coerce")
    usable = latitudes.between(33, 37) & longitudes.between(-85, -75)

    compared = historical.loc[usable]
    compared_zips = zips.loc[usable]
    compared_study_zip = study_zip.loc[usable]
    shapely.prepare(boundary)
    points = shapely.points(
        longitudes.loc[usable].to_numpy(dtype=float),
        latitudes.loc[usable].to_numpy(dtype=float),
    )
    in_county = pd.Series(shapely.covers(boundary, points), index=compared.index)
    outside_county = ~in_county
    in_study_zip = compared_study_zip
    outside_study_zip = ~in_study_zip

    return {
        "sales_source": _file_identity(sales_path),
        "boundary_source": _file_identity(boundary_path),
        "boundary_geometry_type": boundary.geom_type,
        "boundary_bounds_lon_lat": [round(value, 6) for value in boundary.bounds],
        "boundary_points_count_as_inside": True,
        "plausible_coordinate_bounds_lon_lat": [-85, 33, -75, 37],
        "historical_sale_filter": (
            "exact-deduplicated past sale with valid date and positive finite price"
        ),
        "source_rows": len(sales),
        "exact_duplicate_rows": len(sales) - len(unique),
        "historical_sale_rows": len(historical),
        "unusable_coordinate_rows": int((~usable).sum()),
        "compared_rows": len(compared),
        "in_county_rows": int(in_county.sum()),
        "outside_county_rows": int(outside_county.sum()),
        "zip_boundary_comparison": {
            "in_county_in_study_zip": int((in_county & in_study_zip).sum()),
            "in_county_outside_study_zip": int((in_county & outside_study_zip).sum()),
            "outside_county_in_study_zip": int((outside_county & in_study_zip).sum()),
            "outside_county_outside_study_zip": int(
                (outside_county & outside_study_zip).sum()
            ),
        },
        "in_county_outside_study_zip_by_zip": _counts_by_zip(
            compared_zips, in_county & outside_study_zip
        ),
        "outside_county_in_study_zip_by_zip": _counts_by_zip(
            compared_zips, outside_county & in_study_zip
        ),
        "study_zips": list(STUDY_ZIPS),
        "scope_note": (
            "Historical sales are broader than the prepared residential cohort"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Durham sale geography")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/processed/geography_audit.json")
    )
    args = parser.parse_args()
    try:
        report = audit_geography(args.raw_dir)
    except (FileNotFoundError, ValueError, pd.errors.ParserError) as exc:
        parser.error(str(exc))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote geographic audit to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
