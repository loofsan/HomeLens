"""Aggregate reported offenses by police beat and year, without incident records.

Reads the City of Durham crime table export and police-beat polygons, counts
offense records per beat, calendar year, and category, and writes a simplified
GeoJSON with aggregate counts only. No addresses, identifiers, or incident rows
are written.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, cast

import pandas as pd
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from homelens.data.inventory import _file_identity, _read_csv, _require_columns
from homelens.data.neighborhood_inventory import CRIME_CSV
from homelens.data.police_beats import BEATS_FILE, SOURCE_LAYER, _load_beats

# FBI UCR summary categories expressed as NIBRS offense codes.
CATEGORIES: dict[str, dict[str, Any]] = {
    "violent": {
        "label": "Violent offenses",
        "definition": (
            "FBI violent crime: murder and nonnegligent manslaughter, rape, "
            "robbery, and aggravated assault"
        ),
        "codes": ["09A", "11A", "11B", "11C", "120", "13A"],
    },
    "property": {
        "label": "Property offenses",
        "definition": (
            "FBI property crime: burglary, larceny-theft, motor vehicle theft, "
            "and arson"
        ),
        "codes": [
            "200",
            "220",
            "23A",
            "23B",
            "23C",
            "23D",
            "23E",
            "23F",
            "23G",
            "23H",
            "240",
        ],
    },
}
CODE_CATEGORY = {
    code: name for name, spec in CATEGORIES.items() for code in spec["codes"]
}
SIMPLIFY_TOLERANCE_DEGREES = 0.00005
KM_PER_DEGREE_LAT = 110.574
KM_PER_DEGREE_LON_AT_EQUATOR = 111.320
NOTES = [
    "Counts are offense records in the City of Durham Police Department's public "
    "crime table, grouped by the police beat recorded on each report.",
    "Beats cover the city police jurisdiction only; county areas outside city "
    "limits are not included.",
    "The public table under-represents some offenses (for example, very few "
    "homicide records), so these are not complete crime statistics.",
    "Beat boundaries are the current layer and may differ from boundaries at the "
    "time of a report.",
    "Counts describe whole beats, not the risk at any specific home or street.",
    "A beat with no counted records in any year is shown as having no linked "
    "reports, not as having no crime.",
]


def _area_km2(geometry: BaseGeometry) -> float:
    """Approximate area from WGS84 degrees with a local equal-area scaling."""
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    latitude = math.radians((min_lat + max_lat) / 2)
    return (
        geometry.area
        * KM_PER_DEGREE_LAT
        * KM_PER_DEGREE_LON_AT_EQUATOR
        * math.cos(latitude)
    )


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    return value


def _districts(path: Path) -> dict[str, str]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    districts: dict[str, set[str]] = defaultdict(set)
    for feature in document["features"]:
        properties = feature["properties"]
        district = properties.get("LAWDIST")
        if isinstance(district, str) and district.strip():
            districts[str(int(properties["LAWBEAT"]))].add(district.strip())
    return {code: sorted(values)[0] for code, values in districts.items() if values}


def _report_dates(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.strip().str.slice(0, 10)
    return pd.to_datetime(text, format="%Y/%m/%d", errors="coerce")


def aggregate_crime_by_beat(raw_dir: Path) -> dict[str, Any]:
    beats_path = raw_dir / BEATS_FILE
    crime_path = raw_dir / CRIME_CSV
    polygons: dict[str, list[BaseGeometry]] = defaultdict(list)
    for beat_id, polygon in _load_beats(beats_path):
        polygons[beat_id].append(polygon)
    districts = _districts(beats_path)

    columns = ("BEAT", "UCR_CODE", "DATE_REPT")
    crime = _read_csv(crime_path, columns)
    _require_columns(crime, crime_path, columns)
    beat = crime["BEAT"].astype("string").str.strip().fillna("")
    code = crime["UCR_CODE"].astype("string").str.strip().fillna("")
    reported = _report_dates(crime["DATE_REPT"])

    category = code.map(CODE_CATEGORY)
    in_scope = category.notna()
    missing_beat = in_scope & beat.eq("")
    known_beat = beat.isin(set(polygons))
    unmatched = in_scope & ~missing_beat & ~known_beat
    invalid_date = in_scope & known_beat & reported.isna()
    counted = in_scope & known_beat & reported.notna()

    counts: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    frame = pd.DataFrame(
        {
            "beat": beat[counted],
            "category": category[counted],
            "year": reported[counted].dt.year.astype(int).astype(str),
        }
    )
    grouped = frame.groupby(["beat", "year", "category"]).size()
    for key, size in grouped.items():
        row_beat, row_year, row_category = cast(tuple[str, str, str], key)
        counts[str(row_beat)][str(row_year)][str(row_category)] = int(size)

    valid_dates = reported.dropna()
    if valid_dates.empty:
        raise ValueError(f"{crime_path.name} has no valid report dates")
    first = valid_dates.min().date()
    last = valid_dates.max().date()
    years = []
    for year in range(first.year, last.year + 1):
        complete = first <= date(year, 1, 1) and last >= date(year, 12, 31)
        years.append(
            {
                "year": year,
                "complete": complete,
                "first_report_date": max(first, date(year, 1, 1)).isoformat(),
                "last_report_date": min(last, date(year, 12, 31)).isoformat(),
            }
        )

    features = []
    for beat_code in sorted(polygons, key=int):
        merged = unary_union(polygons[beat_code])
        simplified = merged.simplify(SIMPLIFY_TOLERANCE_DEGREES, preserve_topology=True)
        per_year = {
            str(item["year"]): {
                name: counts[beat_code][str(item["year"])].get(name, 0)
                for name in CATEGORIES
            }
            for item in years
        }
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "beat": beat_code,
                    "district": districts.get(beat_code),
                    "area_km2": round(_area_km2(merged), 3),
                    "has_records": any(
                        value for year in per_year.values() for value in year.values()
                    ),
                    "counts": per_year,
                },
                "geometry": _rounded(mapping(simplified)),
            }
        )

    unmatched_codes = beat[unmatched].value_counts().sort_index()
    return {
        "type": "FeatureCollection",
        "metadata": {
            "crime_source": _file_identity(crime_path),
            "beat_source": _file_identity(beats_path),
            "source_layer": SOURCE_LAYER,
            "record_unit": "offense_record",
            "categories": CATEGORIES,
            "years": years,
            "rows": {
                "total": len(crime),
                "in_category_scope": int(in_scope.sum()),
                "counted": int(counted.sum()),
                "missing_beat": int(missing_beat.sum()),
                "unmatched_beat": int(unmatched.sum()),
                "unmatched_beat_by_code": {
                    str(key): int(value) for key, value in unmatched_codes.items()
                },
                "invalid_report_date": int(invalid_date.sum()),
            },
            "area_method": "WGS84 area scaled at each beat's mid-latitude",
            "notes": NOTES,
        },
        "features": features,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate Durham reported offenses by police beat"
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/processed/crime_beats.geojson")
    )
    args = parser.parse_args()
    try:
        report = aggregate_crime_by_beat(args.raw_dir)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    rows = report["metadata"]["rows"]
    print(
        f"Wrote {len(report['features'])} beats and {rows['counted']} counted "
        f"offense records to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
