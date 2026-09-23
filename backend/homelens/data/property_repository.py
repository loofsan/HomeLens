"""Read-only SQLite adapter for historical property sales."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any, cast

from homelens.domain.property import (
    CATALOG_SCHEMA_VERSION,
    CatalogSource,
    HistoricalSale,
    PropertyPage,
    PropertyQuery,
    PropertyType,
)


class CatalogUnavailableError(Exception):
    """The offline catalog is absent or incompatible with this API."""


def _sale(row: sqlite3.Row) -> HistoricalSale:
    return HistoricalSale(
        id=str(row["id"]),
        sale_date=date.fromisoformat(row["sale_date"]),
        sold_price_usd=float(row["sold_price_usd"]),
        beds=float(row["beds"]),
        baths=float(row["baths"]),
        square_feet=float(row["square_feet"]),
        year_built=int(row["year_built"]),
        property_type=cast(PropertyType, row["property_type"]),
        address=str(row["address"]),
        city=str(row["city"]),
        state="NC",
        zip=str(row["zip"]),
        latitude=float(row["latitude"]),
        longitude=float(row["longitude"]),
        source_url=row["source_url"],
    )


def _source(connection: sqlite3.Connection) -> CatalogSource:
    metadata = dict(connection.execute("SELECT key, value FROM catalog_metadata"))
    if (
        metadata.get("record_kind") != "historical_sale"
        or not metadata.get("source_sha256")
        or not metadata.get("boundary_sha256")
        or "sale_date_max" not in metadata
    ):
        raise CatalogUnavailableError("catalog metadata is incomplete")
    return CatalogSource(
        name="Redfin sold-home CSV export",
        latest_sale_date=metadata["sale_date_max"] or None,
        source_sha256=metadata["source_sha256"],
        boundary_sha256=metadata["boundary_sha256"],
    )


class SqlitePropertyRepository:
    def __init__(self, database: Path) -> None:
        self._database = database

    def _connect(self) -> sqlite3.Connection:
        if not self._database.is_file():
            raise CatalogUnavailableError("historical sales catalog is missing")
        uri = self._database.resolve().as_uri() + "?mode=ro"
        connection = None
        try:
            connection = sqlite3.connect(uri, uri=True)
            connection.row_factory = sqlite3.Row
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != CATALOG_SCHEMA_VERSION:
                connection.close()
                raise CatalogUnavailableError("historical sales schema is incompatible")
            return connection
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise CatalogUnavailableError(
                "historical sales catalog is unreadable"
            ) from exc

    def search(self, query: PropertyQuery) -> PropertyPage:
        clauses = ["record_kind = 'historical_sale'"]
        values: list[Any] = []
        for column, value, operator in (
            ("sold_price_usd", query.min_price, ">="),
            ("sold_price_usd", query.max_price, "<="),
            ("beds", query.min_beds, ">="),
            ("baths", query.min_baths, ">="),
            ("zip", query.zip, "="),
        ):
            if value is not None:
                clauses.append(f"{column} {operator} ?")
                values.append(value)
        if query.bounds is not None:
            clauses.extend(
                (
                    "latitude BETWEEN ? AND ?",
                    "longitude BETWEEN ? AND ?",
                )
            )
            values.extend(
                (
                    query.bounds.south,
                    query.bounds.north,
                    query.bounds.west,
                    query.bounds.east,
                )
            )
        where = " AND ".join(clauses)
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN")
                source = _source(connection)
                total = int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM historical_sales WHERE {where}", values
                    ).fetchone()[0]
                )
                rows = connection.execute(
                    f"""SELECT * FROM historical_sales WHERE {where}
                    ORDER BY sale_date DESC, id ASC LIMIT ? OFFSET ?""",
                    [*values, query.page_size, (query.page - 1) * query.page_size],
                ).fetchall()
                return PropertyPage(
                    items=[_sale(row) for row in rows],
                    total=total,
                    page=query.page,
                    page_size=query.page_size,
                    source=source,
                )
        except (sqlite3.Error, ValueError) as exc:
            raise CatalogUnavailableError(
                "historical sales catalog is unreadable"
            ) from exc

    def get(self, property_id: str) -> tuple[HistoricalSale | None, CatalogSource]:
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN")
                source = _source(connection)
                row = connection.execute(
                    "SELECT * FROM historical_sales WHERE id = ?", (property_id,)
                ).fetchone()
                return (_sale(row) if row is not None else None), source
        except (sqlite3.Error, ValueError) as exc:
            raise CatalogUnavailableError(
                "historical sales catalog is unreadable"
            ) from exc
