"""Audit police-beat polygons and their code linkage to crime records."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from homelens.data.inventory import _file_identity, _read_csv, _require_columns
from homelens.data.neighborhood_inventory import CRIME_CSV

BEATS_FILE = "durham_police_beats.geojson"
SOURCE_LAYER = (
    "https://webgis.durhamnc.gov/server/rest/services/"
    "PublicServices/Public_Safety/MapServer/8"
)


def _beat_code(raw: object) -> str:
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise ValueError(f"Invalid LAWBEAT code: {raw!r}")
    value = str(raw).strip()
    if not value.isascii() or not value.isdigit() or int(value) < 1:
        raise ValueError(f"Invalid LAWBEAT code: {raw!r}")
    return str(int(value))


def _load_beats(path: Path) -> list[tuple[str, BaseGeometry]]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing police-beat file: {path}")
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise ValueError(f"{path.name} must be a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError(f"{path.name} must contain police-beat features")

    beats: list[tuple[str, BaseGeometry]] = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"{path.name} feature {index} is not a GeoJSON Feature")
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            raise ValueError(f"{path.name} feature {index} lacks beat geometry")
        code = _beat_code(properties.get("LAWBEAT"))
        try:
            polygon = shape(geometry)
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError(
                f"{path.name} feature {index} has invalid coordinates"
            ) from exc
        if (
            polygon.geom_type not in {"Polygon", "MultiPolygon"}
            or polygon.is_empty
            or not polygon.is_valid
        ):
            raise ValueError(f"{path.name} feature {index} is not a valid polygon")
        min_lon, min_lat, max_lon, max_lat = polygon.bounds
        if not (-80 < min_lon < max_lon < -78 and 35 < min_lat < max_lat < 37):
            raise ValueError(
                f"{path.name} feature {index} must use Durham-area WGS84 lon/lat"
            )
        beats.append((code, polygon))
    return beats


def _overlap_counts(
    beats: list[tuple[str, BaseGeometry]],
) -> dict[str, Any]:
    same_code = 0
    different_code = 0
    largest_different_code_fraction = 0.0
    different_code_pairs: set[tuple[str, str]] = set()
    for index, (first_code, first) in enumerate(beats):
        left, bottom, right, top = first.bounds
        for second_code, second in beats[index + 1 :]:
            other_left, other_bottom, other_right, other_top = second.bounds
            if (
                right <= other_left
                or other_right <= left
                or top <= other_bottom
                or other_top <= bottom
            ):
                continue
            overlap_area = first.intersection(second).area
            if overlap_area <= 0:
                continue
            if first_code == second_code:
                same_code += 1
            else:
                different_code += 1
                largest_different_code_fraction = max(
                    largest_different_code_fraction,
                    overlap_area / min(first.area, second.area),
                )
                pair = (
                    (first_code, second_code)
                    if first_code < second_code
                    else (second_code, first_code)
                )
                different_code_pairs.add(pair)
    return {
        "same_beat_feature_pairs": same_code,
        "different_beat_feature_pairs": different_code,
        "largest_different_beat_overlap_fraction_of_smaller_feature": round(
            largest_different_code_fraction, 12
        ),
        "different_beat_code_pairs": [
            list(pair) for pair in sorted(different_code_pairs)
        ],
    }


def audit_police_beats(raw_dir: Path) -> dict[str, Any]:
    beats_path = raw_dir / BEATS_FILE
    crime_path = raw_dir / CRIME_CSV
    beats = _load_beats(beats_path)
    crime = _read_csv(crime_path, ("BEAT",))
    _require_columns(crime, crime_path, ("BEAT",))

    feature_counts = Counter(code for code, _ in beats)
    beat_codes = set(feature_counts)
    crime_codes = crime["BEAT"].astype("string").str.strip().fillna("")
    missing = crime_codes.eq("")
    matched = crime_codes.isin(beat_codes)
    unmatched = crime_codes.loc[~missing & ~matched].value_counts().sort_index()
    crime_nonblank_codes = set(crime_codes.loc[~missing])

    return {
        "crime_source": _file_identity(crime_path),
        "beat_source": _file_identity(beats_path),
        "source_layer": SOURCE_LAYER,
        "boundary_effective_date": None,
        "historical_boundary_alignment": "unverified",
        "beat_geometry": {
            "features": len(beats),
            "unique_codes": len(beat_codes),
            "polygon_features": sum(
                polygon.geom_type == "Polygon" for _, polygon in beats
            ),
            "multipolygon_features": sum(
                polygon.geom_type == "MultiPolygon" for _, polygon in beats
            ),
            "codes_with_multiple_features": {
                code: count
                for code, count in sorted(feature_counts.items())
                if count > 1
            },
            **_overlap_counts(beats),
        },
        "crime_beat_join": {
            "rows": len(crime),
            "matched_rows": int(matched.sum()),
            "missing_beat_rows": int(missing.sum()),
            "unmatched_nonblank_rows": int(unmatched.sum()),
            "unmatched_by_code": {
                str(code): int(count) for code, count in unmatched.items()
            },
            "crime_codes_without_geometry": sorted(crime_nonblank_codes - beat_codes),
            "geometry_codes_without_crime": sorted(beat_codes - crime_nonblank_codes),
        },
        "scope_note": (
            "Code coverage supports a beat-level source audit only; incident-point, "
            "historical-boundary, property-level, and ZIP-level crime claims "
            "are not established"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Durham police-beat geography")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/processed/police_beats_audit.json")
    )
    args = parser.parse_args()
    try:
        report = audit_police_beats(args.raw_dir)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote police-beat audit to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
