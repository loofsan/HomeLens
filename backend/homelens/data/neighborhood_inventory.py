"""Audit local crime and demographic exports without exposing source records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from homelens.data.inventory import (
    _base_report,
    _file_identity,
    _read_csv,
    _require_columns,
)

CRIME_CSV = "DPD_Crime_(table_only).csv"
CRIME_GEOJSON = "City_Crime_(External_Use).geojson"
ACS_PATTERN = "ACSDP1Y2023.DP05*.csv"
CRIME_COLUMNS = (
    "OBJECTID",
    "INCI_ID",
    "DATE_REPT",
    "YEARSTAMP",
    "MONTHSTAMP",
    "DIST",
    "BEAT",
    "ADDRESS2",
)
CRIME_TEXT_COLUMNS = CRIME_COLUMNS + (
    "HOUR_REPT",
    "REPORTEDAS",
    "UCR_CODE",
    "CHRGDESC",
    "ATTM_COMP",
    "PREMISE",
    "WEAPON",
    "CSSTATUS",
)


def _acs_files(raw_dir: Path) -> list[Path]:
    matches = sorted(raw_dir.glob(ACS_PATTERN))
    if not matches:
        raise ValueError(f"Expected at least one {ACS_PATTERN} file")
    return matches


def _read_geojson(path: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing raw file: {path}")
    with path.open(encoding="utf-8-sig") as source:
        document = json.load(source)
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise ValueError(f"{path.name} must be a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError(f"{path.name} must contain features")
    if any(
        not isinstance(item, dict) or not isinstance(item.get("properties"), dict)
        for item in features
    ):
        raise ValueError(f"{path.name} contains features without properties")
    properties = pd.DataFrame(item["properties"] for item in features)
    _require_columns(properties, path, CRIME_COLUMNS)
    return document, properties


def _ids(frame: pd.DataFrame) -> pd.Series[Any]:
    return frame["OBJECTID"].astype("string").str.strip()


def _matching_fields(csv_data: pd.DataFrame, geo_data: pd.DataFrame) -> dict[str, int]:
    csv_indexed = csv_data.assign(_id=_ids(csv_data))
    geo_indexed = geo_data.assign(_id=_ids(geo_data))
    csv_indexed = (
        csv_indexed.loc[csv_indexed["_id"].notna() & csv_indexed["_id"].ne("")]
        .drop_duplicates("_id")
        .set_index("_id")
    )
    geo_indexed = (
        geo_indexed.loc[geo_indexed["_id"].notna() & geo_indexed["_id"].ne("")]
        .drop_duplicates("_id")
        .set_index("_id")
    )
    common = sorted(set(csv_indexed.index) & set(geo_indexed.index))
    left = csv_indexed.loc[common]
    right = geo_indexed.loc[common]
    mismatches: dict[str, int] = {}
    for column in sorted(set(csv_data.columns) & set(geo_data.columns)):
        if column == "OBJECTID":
            continue
        if column == "DATE_REPT":
            csv_dates = pd.to_datetime(
                left[column], format="%Y/%m/%d %H:%M:%S%z", utc=True, errors="coerce"
            )
            geo_dates = pd.to_datetime(
                right[column], format="ISO8601", utc=True, errors="coerce"
            )
            same = csv_dates.eq(geo_dates) | (csv_dates.isna() & geo_dates.isna())
        else:
            csv_text = left[column].astype("string").fillna("").str.strip()
            geo_text = right[column].astype("string").fillna("").str.strip()
            same = csv_text.eq(geo_text)
        mismatches[column] = int((~same).sum())
    return mismatches


def inspect_neighborhood_sources(raw_dir: Path) -> dict[str, Any]:
    csv_path = raw_dir / CRIME_CSV
    geo_path = raw_dir / CRIME_GEOJSON
    crime = _read_csv(csv_path, CRIME_TEXT_COLUMNS)
    _require_columns(crime, csv_path, CRIME_COLUMNS)
    document, properties = _read_geojson(geo_path)
    acs_files = _acs_files(raw_dir)

    dates = pd.to_datetime(
        crime["DATE_REPT"], format="%Y/%m/%d %H:%M:%S%z", utc=True, errors="coerce"
    )
    years = pd.to_numeric(crime["YEARSTAMP"], errors="coerce")
    nonzero_years = years.notna() & years.ne(0) & dates.notna()
    csv_ids = _ids(crime)
    geo_ids = _ids(properties)
    features = document["features"]
    geometry_present = sum(item.get("geometry") is not None for item in features)
    acs_reports: dict[str, dict[str, Any]] = {}
    all_geographies: set[str] = set()
    for acs_path in acs_files:
        acs = _read_csv(acs_path, ("Label (Grouping)",))
        _require_columns(acs, acs_path, ("Label (Grouping)",))
        geographies = sorted(
            {name.split("!!", 1)[0].strip() for name in acs.columns[1:] if "!!" in name}
        )
        all_geographies.update(geographies)
        acs_reports[acs_path.name] = {
            **_file_identity(acs_path),
            "rows": len(acs),
            "column_names": list(acs.columns),
            "geographies": geographies,
        }
    durham_present = "Durham County, North Carolina" in all_geographies

    crime_report = _base_report(crime)
    crime_report.update(_file_identity(csv_path))
    crime_report.update(
        {
            "unique_objectids": int(csv_ids.nunique()),
            "duplicate_objectids": int(csv_ids.duplicated().sum()),
            "duplicate_incident_ids": int(crime["INCI_ID"].duplicated().sum()),
            "valid_reported_dates": int(dates.notna().sum()),
            "reported_date_range": (
                [dates.min().date().isoformat(), dates.max().date().isoformat()]
                if dates.notna().any()
                else [None, None]
            ),
            "yearstamp_zero_rows": int(years.eq(0).sum()),
            "yearstamp_invalid_rows": int(years.isna().sum()),
            "nonzero_yearstamp_date_mismatches": int(
                years[nonzero_years].ne(dates[nonzero_years].dt.year).sum()
            ),
        }
    )

    geo_report = {
        **_file_identity(geo_path),
        "features": len(features),
        "geometry_present_features": geometry_present,
        "geometry_missing_features": len(features) - geometry_present,
        "property_columns": sorted(properties.columns.tolist()),
        "unique_objectids": int(geo_ids.nunique()),
        "duplicate_objectids": int(geo_ids.duplicated().sum()),
        "crs_name": (
            document["crs"].get("properties", {}).get("name")
            if isinstance(document.get("crs"), dict)
            else None
        ),
    }
    mismatch_counts = _matching_fields(crime, properties)
    same_ids = (
        len(csv_ids) == len(geo_ids)
        and csv_ids.nunique() == len(csv_ids)
        and geo_ids.nunique() == len(geo_ids)
        and set(csv_ids.dropna()) == set(geo_ids.dropna())
    )
    return {
        "crime_csv": crime_report,
        "crime_geojson": geo_report,
        "cross_export": {
            "same_objectid_set": same_ids,
            "same_property_columns": set(crime.columns) == set(properties.columns),
            "property_mismatches_by_column": mismatch_counts,
            "same_nonspatial_records": (
                same_ids
                and set(crime.columns) == set(properties.columns)
                and all(count == 0 for count in mismatch_counts.values())
            ),
        },
        "acs_dp05": {
            "files": acs_reports,
            "geographies": sorted(all_geographies),
            "durham_county_present": durham_present,
        },
        "readiness": {
            "crime_has_any_geometry": geometry_present > 0,
            "durham_demographics_present": durham_present,
            "zip_level_crime_supported": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit HomeLens crime and ACS source exports"
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/neighborhood_inventory.json"),
    )
    args = parser.parse_args()
    try:
        report = inspect_neighborhood_sources(args.raw_dir)
    except (
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
        pd.errors.ParserError,
    ) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote neighborhood source inventory to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
