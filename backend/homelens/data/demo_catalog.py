"""Create a separate, explicitly fictional local catalog for repo demos."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from homelens.data.property_catalog import write_catalog
from homelens.domain.property import HistoricalSale, PropertyType

CENTERS: tuple[tuple[str, float, float], ...] = (
    ("27701", 35.996, -78.901),
    ("27703", 35.976, -78.832),
    ("27704", 36.045, -78.862),
    ("27705", 36.027, -78.951),
    ("27707", 35.965, -78.940),
    ("27713", 35.906, -78.924),
)
TYPES: tuple[PropertyType, ...] = (
    "Single Family Residential",
    "Townhouse",
    "Condo/Co-op",
)
SOURCE_HASH = hashlib.sha256(b"homelens-fictional-demo-v1").hexdigest()
COORDINATE_HASH = hashlib.sha256(b"illustrative-points-not-parcels-v1").hexdigest()


def build_demo_catalog() -> tuple[list[HistoricalSale], dict[str, Any]]:
    records = []
    for index in range(24):
        zip_code, latitude, longitude = CENTERS[index % len(CENTERS)]
        sale_date = date(2024 + index // 12, index % 12 + 1, 15)
        records.append(
            HistoricalSale(
                id="sale_"
                + hashlib.sha256(f"homelens-demo-v1-{index}".encode()).hexdigest()[:32],
                sale_date=sale_date,
                sold_price_usd=float(185000 + (index * 37000) % 540000),
                beds=float(2 + index % 4),
                baths=float(1 + index % 3),
                square_feet=float(950 + index * 105),
                year_built=1985 + index,
                property_type=TYPES[index % len(TYPES)],
                address=f"Fictional example {index + 1:02d}",
                city="Durham",
                state="NC",
                zip=zip_code,
                latitude=latitude + (index // len(CENTERS)) * 0.001,
                longitude=longitude - (index // len(CENTERS)) * 0.001,
                source_url=None,
            )
        )
    return records, {
        "record_kind": "historical_sale",
        "source_name": "Synthetic HomeLens demo records",
        "synthetic": True,
        "source_identity": {"sha256": SOURCE_HASH},
        "boundary_source_identity": {"sha256": COORDINATE_HASH},
        "imported_rows": len(records),
        "sale_date_range": [
            min(record.sale_date for record in records).isoformat(),
            max(record.sale_date for record in records).isoformat(),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create fictional HomeLens demo data")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/processed/demo_catalog.sqlite3"),
    )
    args = parser.parse_args()
    if args.database.name == "property_catalog.sqlite3":
        parser.error("demo data must not use the real catalog filename")
    if args.database.exists() or args.database.is_symlink():
        parser.error("demo catalog already exists; choose a new output path")
    records, report = build_demo_catalog()
    try:
        write_catalog(args.database, records, report)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(f"Created {len(records)} fictional examples at {args.database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
