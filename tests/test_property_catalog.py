import csv
import json
import sqlite3
from pathlib import Path

import pytest
from homelens.data.property_catalog import (
    SOURCE_URL_COLUMN,
    build_catalog,
    write_catalog,
)

FIELDS = (
    "SALE TYPE",
    "SOLD DATE",
    "PRICE",
    "BEDS",
    "BATHS",
    "SQUARE FEET",
    "YEAR BUILT",
    "PROPERTY TYPE",
    "ZIP OR POSTAL CODE",
    "MLS#",
    "STATE OR PROVINCE",
    "ADDRESS",
    "CITY",
    "LATITUDE",
    "LONGITUDE",
    SOURCE_URL_COLUMN,
)


def _raw_dir(tmp_path: Path) -> Path:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "durham_county_boundary.geojson").write_text(
        json.dumps(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-79.2, 35.8],
                            [-78.8, 35.8],
                            [-78.8, 36.2],
                            [-79.2, 36.2],
                            [-79.2, 35.8],
                        ]
                    ],
                },
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    base = {
        "SALE TYPE": "PAST SALE",
        "SOLD DATE": "2024-06-01",
        "PRICE": "350000",
        "BEDS": "3",
        "BATHS": "2",
        "SQUARE FEET": "1200",
        "YEAR BUILT": "1990",
        "PROPERTY TYPE": "Townhouse",
        "ZIP OR POSTAL CODE": "27703",
        "MLS#": "A1",
        "STATE OR PROVINCE": "NC",
        "ADDRESS": "1 Main St",
        "CITY": "Durham",
        "LATITUDE": "36",
        "LONGITUDE": "-79",
        SOURCE_URL_COLUMN: "https://www.redfin.com/NC/Durham/1-Main-St",
    }

    def changed(**values: str) -> dict[str, str]:
        return {**base, **values}

    rows = [
        base,
        base.copy(),
        changed(
            **{
                "MLS#": "B2",
                "ADDRESS": "2 Main St",
                "SOLD DATE": "2023-01-01",
                "ZIP OR POSTAL CODE": "27517",
                SOURCE_URL_COLUMN: "http://www.redfin.com/not-https",
            }
        ),
        changed(**{"MLS#": "C3", "ADDRESS": "3 Main St", "LONGITUDE": "-79.2"}),
        changed(**{"MLS#": "D4", "LONGITUDE": "-79.5"}),
        changed(**{"MLS#": "E5", "SALE TYPE": "FOR SALE"}),
        changed(**{"MLS#": "F6", "ADDRESS": ""}),
        changed(**{"MLS#": "G7", "SOLD DATE": "not-a-date"}),
        changed(**{"MLS#": "H8", "SQUARE FEET": "2"}),
        changed(**{"MLS#": "I9", "LATITUDE": ""}),
    ]
    with (raw_dir / "redfin_data.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return raw_dir


def test_build_catalog_audits_historical_sales_without_study_zip_limit(
    tmp_path: Path,
) -> None:
    raw_dir = _raw_dir(tmp_path)

    records, report = build_catalog(raw_dir)

    assert report["source_rows"] == 10
    assert report["imported_rows"] == 3
    assert report["source_rows"] == report["imported_rows"] + sum(
        report["rejected_rows_by_stage"].values()
    )
    assert report["rejected_rows_by_stage"]["exact_duplicates"] == 1
    assert report["rejected_rows_by_stage"]["outside_county"] == 1
    assert report["rejected_rows_by_stage"]["unusable_coordinates"] == 1
    assert report["record_kind"] == "historical_sale"
    assert report["sale_date_range"] == ["2023-01-01", "2024-06-01"]
    assert report["invalid_source_urls"] == 1
    assert {record.zip for record in records} == {"27517", "27703"}
    assert {record.record_kind for record in records} == {"historical_sale"}
    assert (
        next(record for record in records if record.zip == "27517").source_url is None
    )
    assert any(record.longitude == -79.2 for record in records)
    assert len({record.id for record in records}) == 3
    assert all(record.id.startswith("sale_") for record in records)


def test_catalog_reimport_is_stable_and_failed_replace_rolls_back(
    tmp_path: Path,
) -> None:
    raw_dir = _raw_dir(tmp_path)
    records, report = build_catalog(raw_dir)
    database = tmp_path / "catalog.sqlite3"
    write_catalog(database, records, report)

    repeated, repeated_report = build_catalog(raw_dir)
    assert [record.id for record in repeated] == [record.id for record in records]
    write_catalog(database, repeated, repeated_report)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM historical_sales"
        ).fetchone() == (3,)
        assert connection.execute(
            "SELECT DISTINCT record_kind FROM historical_sales"
        ).fetchall() == [("historical_sale",)]
        assert connection.execute(
            "SELECT value FROM catalog_metadata WHERE key = 'source_sha256'"
        ).fetchone() == (report["source_identity"]["sha256"],)
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)

    with pytest.raises(sqlite3.IntegrityError):
        write_catalog(database, records[:1] * 2, {**report, "imported_rows": 2})
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM historical_sales"
        ).fetchone() == (3,)
