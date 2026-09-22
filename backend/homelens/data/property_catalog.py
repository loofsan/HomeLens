"""Import supplied sold homes into a local, auditable property catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections.abc import Hashable, Mapping
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import shapely

from homelens.domain.property import CATALOG_SCHEMA_VERSION, HistoricalSale

from .boundary import load_county_boundary
from .inventory import (
    REDFIN_COLUMNS,
    _file_identity,
    _normalized_zips,
    _read_csv,
    _require_columns,
)
from .prepare import NUMERIC_FEATURES, RESIDENTIAL_TYPES

SOURCE_URL_COLUMN = (
    "URL (SEE https://www.redfin.com/buy-a-home/comparative-market-analysis "
    "FOR INFO ON PRICING)"
)
SCHEMA_VERSION = CATALOG_SCHEMA_VERSION


def _keep(
    frame: pd.DataFrame,
    mask: pd.Series[Any],
    rejected: dict[str, int],
    reason: str,
) -> pd.DataFrame:
    kept = frame.loc[mask.fillna(False)].copy()
    rejected[reason] = len(frame) - len(kept)
    return kept


def _text(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _source_url(value: Any) -> str | None:
    url = _text(value)
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.hostname in {
        "redfin.com",
        "www.redfin.com",
    }:
        return url
    return None


def _record_id(row: Mapping[Hashable, Any], source_url: str | None) -> str:
    identity = [
        _text(row["MLS#"]),
        row["sale_date"],
        float(row["PRICE"]),
        row["ADDRESS"],
        row["CITY"],
        row["zip"],
        float(row["LATITUDE"]),
        float(row["LONGITUDE"]),
        float(row["BEDS"]),
        float(row["BATHS"]),
        float(row["SQUARE FEET"]),
        int(row["YEAR BUILT"]),
        row["PROPERTY TYPE"],
        source_url,
    ]
    digest = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode())
    return "sale_" + digest.hexdigest()[:32]


def build_catalog(raw_dir: Path) -> tuple[list[HistoricalSale], dict[str, Any]]:
    sales_path = raw_dir / "redfin_data.csv"
    boundary_path = raw_dir / "durham_county_boundary.geojson"
    boundary = load_county_boundary(boundary_path)
    source = _read_csv(sales_path, ("ZIP OR POSTAL CODE", "MLS#"))
    _require_columns(
        source,
        sales_path,
        (
            *REDFIN_COLUMNS,
            "SALE TYPE",
            "STATE OR PROVINCE",
            "ADDRESS",
            "CITY",
            "LATITUDE",
            "LONGITUDE",
        ),
    )

    rejected: dict[str, int] = {}
    frame = source.drop_duplicates().copy()
    rejected["exact_duplicates"] = len(source) - len(frame)
    frame = _keep(
        frame,
        frame["SALE TYPE"].astype("string").str.strip().eq("PAST SALE"),
        rejected,
        "not_past_sale",
    )
    dates = pd.to_datetime(frame["SOLD DATE"], format="mixed", errors="coerce")
    frame = _keep(frame, dates.notna(), rejected, "missing_or_invalid_sale_date")
    frame["sale_date"] = dates.loc[frame.index].dt.strftime("%Y-%m-%d")

    prices = pd.to_numeric(frame["PRICE"], errors="coerce")
    frame = _keep(
        frame,
        prices.gt(0) & prices.lt(float("inf")),
        rejected,
        "missing_invalid_or_nonpositive_price",
    )
    frame["PRICE"] = prices.loc[frame.index]
    frame = _keep(
        frame,
        frame["PROPERTY TYPE"].isin(RESIDENTIAL_TYPES),
        rejected,
        "outside_initial_residential_types",
    )
    frame = _keep(
        frame,
        frame["STATE OR PROVINCE"].astype("string").str.strip().eq("NC"),
        rejected,
        "outside_north_carolina",
    )

    for column in ("ADDRESS", "CITY"):
        frame[column] = frame[column].astype("string").str.strip()
    frame = _keep(
        frame,
        frame["ADDRESS"].notna()
        & frame["ADDRESS"].ne("")
        & frame["CITY"].notna()
        & frame["CITY"].ne(""),
        rejected,
        "missing_address_or_city",
    )

    frame["zip"] = _normalized_zips(frame["ZIP OR POSTAL CODE"])
    frame = _keep(
        frame,
        frame["zip"].str.fullmatch(r"\d{5}"),
        rejected,
        "invalid_zip_format",
    )
    for column in (*NUMERIC_FEATURES, "LATITUDE", "LONGITUDE"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = _keep(
        frame,
        frame[list(NUMERIC_FEATURES)].notna().all(axis=1),
        rejected,
        "missing_core_features",
    )
    sale_year = pd.to_datetime(frame["sale_date"]).dt.year
    plausible = (
        frame["BEDS"].ge(0)
        & frame["BEDS"].lt(float("inf"))
        & frame["BATHS"].gt(0)
        & frame["BATHS"].lt(float("inf"))
        & frame["SQUARE FEET"].ge(300)
        & frame["SQUARE FEET"].lt(float("inf"))
        & frame["YEAR BUILT"].ge(1800)
        & frame["YEAR BUILT"].le(sale_year)
        & frame["YEAR BUILT"].mod(1).eq(0)
    )
    frame = _keep(frame, plausible, rejected, "implausible_core_features")
    frame = _keep(
        frame,
        frame["LATITUDE"].between(33, 37) & frame["LONGITUDE"].between(-85, -75),
        rejected,
        "unusable_coordinates",
    )
    shapely.prepare(boundary)
    points = shapely.points(
        frame["LONGITUDE"].to_numpy(dtype=float),
        frame["LATITUDE"].to_numpy(dtype=float),
    )
    frame = _keep(
        frame,
        pd.Series(shapely.covers(boundary, points), index=frame.index),
        rejected,
        "outside_county",
    )

    seen: set[str] = set()
    records: list[HistoricalSale] = []
    invalid_source_urls = 0
    for row in frame.to_dict("records"):
        raw_url = row.get(SOURCE_URL_COLUMN)
        source_url = _source_url(raw_url)
        if _text(raw_url) and source_url is None:
            invalid_source_urls += 1
        record_id = _record_id(row, source_url)
        if record_id in seen:
            continue
        seen.add(record_id)
        records.append(
            HistoricalSale(
                id=record_id,
                sale_date=date.fromisoformat(row["sale_date"]),
                sold_price_usd=float(row["PRICE"]),
                beds=float(row["BEDS"]),
                baths=float(row["BATHS"]),
                square_feet=float(row["SQUARE FEET"]),
                year_built=int(row["YEAR BUILT"]),
                property_type=row["PROPERTY TYPE"],
                address=row["ADDRESS"],
                city=row["CITY"],
                state="NC",
                zip=row["zip"],
                latitude=float(row["LATITUDE"]),
                longitude=float(row["LONGITUDE"]),
                source_url=source_url,
            )
        )
    rejected["duplicate_record_identity"] = len(frame) - len(records)
    records.sort(key=lambda record: (record.sale_date, record.zip, record.id))
    report: dict[str, Any] = {
        "record_kind": "historical_sale",
        "source_file": sales_path.name,
        "source_identity": _file_identity(sales_path),
        "boundary_source_identity": _file_identity(boundary_path),
        "source_rows": len(source),
        "rejected_rows_by_stage": rejected,
        "imported_rows": len(records),
        "sale_date_range": [
            records[0].sale_date.isoformat() if records else None,
            records[-1].sale_date.isoformat() if records else None,
        ],
        "geography_scope": "sales inside supplied Durham County polygon",
        "property_types": list(RESIDENTIAL_TYPES),
        "invalid_source_urls": invalid_source_urls,
        "schema_version": SCHEMA_VERSION,
    }
    return records, report


def write_catalog(
    database: Path, records: list[HistoricalSale], report: dict[str, Any]
) -> None:
    if any(record.record_kind != "historical_sale" for record in records):
        raise ValueError("catalog accepts historical sales only")
    if len(records) != report["imported_rows"]:
        raise ValueError("catalog records do not match import audit")
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_sales (
                id TEXT PRIMARY KEY,
                record_kind TEXT NOT NULL CHECK (record_kind = 'historical_sale'),
                sale_date TEXT NOT NULL,
                sold_price_usd REAL NOT NULL CHECK (sold_price_usd > 0),
                beds REAL NOT NULL,
                baths REAL NOT NULL,
                square_feet REAL NOT NULL,
                year_built INTEGER NOT NULL,
                property_type TEXT NOT NULL,
                address TEXT NOT NULL,
                city TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state = 'NC'),
                zip TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                source_url TEXT
            )
            """
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS catalog_metadata (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )"""
        )
        connection.execute("DELETE FROM historical_sales")
        connection.executemany(
            """
            INSERT INTO historical_sales VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    record.id,
                    record.record_kind,
                    record.sale_date.isoformat(),
                    record.sold_price_usd,
                    record.beds,
                    record.baths,
                    record.square_feet,
                    record.year_built,
                    record.property_type,
                    record.address,
                    record.city,
                    record.state,
                    record.zip,
                    record.latitude,
                    record.longitude,
                    record.source_url,
                )
                for record in records
            ],
        )
        connection.execute("DELETE FROM catalog_metadata")
        connection.executemany(
            "INSERT INTO catalog_metadata VALUES (?, ?)",
            [
                ("schema_version", str(SCHEMA_VERSION)),
                ("record_kind", "historical_sale"),
                ("source_sha256", report["source_identity"]["sha256"]),
                ("boundary_sha256", report["boundary_source_identity"]["sha256"]),
                ("sale_date_max", report["sale_date_range"][1] or ""),
            ],
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.execute(
            """CREATE INDEX IF NOT EXISTS historical_sales_zip_date
            ON historical_sales (zip, sale_date)"""
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Import historical HomeLens sales")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--database", type=Path, default=Path("data/processed/property_catalog.sqlite3")
    )
    parser.add_argument(
        "--audit", type=Path, default=Path("data/processed/property_catalog_audit.json")
    )
    args = parser.parse_args()
    try:
        records, report = build_catalog(args.raw_dir)
        write_catalog(args.database, records, report)
        args.audit.parent.mkdir(parents=True, exist_ok=True)
        args.audit.write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    except (FileNotFoundError, ValueError, sqlite3.Error, pd.errors.ParserError) as exc:
        parser.error(str(exc))
    print(f"Imported {len(records)} historical sales into {args.database}")
    print(f"Wrote aggregate import audit to {args.audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
