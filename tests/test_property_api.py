import sqlite3
from datetime import date
from pathlib import Path

import pytest
from flask import Flask
from homelens import create_app
from homelens.data.property_catalog import write_catalog
from homelens.domain.property import HistoricalSale


def _app(tmp_path: Path) -> Flask:
    database = tmp_path / "sales.sqlite3"
    base = {
        "sold_price_usd": 350000.0,
        "beds": 3.0,
        "baths": 2.0,
        "square_feet": 1200.0,
        "year_built": 1990,
        "property_type": "Townhouse",
        "city": "Durham",
        "state": "NC",
        "source_url": "https://www.redfin.com/NC/Durham/1-Main-St",
    }
    records = [
        HistoricalSale(
            id="sale_" + "a" * 32,
            sale_date=date(2024, 6, 1),
            address="1 Main St",
            zip="27703",
            latitude=36.0,
            longitude=-79.0,
            **base,
        ),
        HistoricalSale(
            id="sale_" + "b" * 32,
            sale_date=date(2024, 6, 1),
            address="2 Main St",
            zip="27705",
            latitude=36.1,
            longitude=-79.1,
            **{**base, "sold_price_usd": 500000.0, "beds": 4.0, "baths": 3.0},
        ),
        HistoricalSale(
            id="sale_" + "c" * 32,
            sale_date=date(2023, 1, 1),
            address="3 Main St",
            zip="27517",
            latitude=35.9,
            longitude=-79.0,
            **{**base, "sold_price_usd": 220000.0, "beds": 2.0, "baths": 1.0},
        ),
    ]
    report = {
        "imported_rows": len(records),
        "source_identity": {"sha256": "a" * 64},
        "boundary_source_identity": {"sha256": "b" * 64},
        "sale_date_range": ["2023-01-01", "2024-06-01"],
    }
    write_catalog(database, records, report)
    return create_app({"TESTING": True, "PROPERTY_CATALOG_PATH": database})


def test_search_and_detail_label_historical_data_and_use_stable_pagination(
    tmp_path: Path,
) -> None:
    client = _app(tmp_path).test_client()

    first = client.get("/api/properties?page_size=2")
    assert first.status_code == 200
    payload = first.get_json()
    assert payload["total"] == 3
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert [record["id"] for record in payload["items"]] == [
        "sale_" + "a" * 32,
        "sale_" + "b" * 32,
    ]
    assert payload["items"][0]["sale_date"] == "2024-06-01"
    assert payload["items"][0]["record_kind"] == "historical_sale"
    assert payload["source"] == {
        "name": "Redfin sold-home CSV export",
        "latest_sale_date": "2024-06-01",
        "source_sha256": "a" * 64,
        "record_kind": "historical_sale",
        "active_listings": False,
    }

    second = client.get("/api/properties?page_size=2&page=2").get_json()
    assert second["total"] == 3
    assert [record["id"] for record in second["items"]] == ["sale_" + "c" * 32]
    assert client.get("/api/properties?page=9").get_json()["items"] == []

    detail = client.get("/api/properties/sale_" + "b" * 32)
    assert detail.status_code == 200
    assert detail.get_json()["property"]["sold_price_usd"] == 500000.0
    assert detail.get_json()["source"]["active_listings"] is False
    missing = client.get("/api/properties/sale_" + "f" * 32)
    assert missing.status_code == 404
    assert missing.get_json()["error"]["code"] == "property_not_found"


def test_search_combines_filters_and_reports_empty_result(tmp_path: Path) -> None:
    client = _app(tmp_path).test_client()
    response = client.get(
        "/api/properties?min_price=300000&max_price=400000&min_beds=3"
        "&min_baths=2&zip=27703&south=35.95&west=-79.05&north=36.05&east=-78.95"
    )
    assert response.status_code == 200
    assert response.get_json()["total"] == 1
    assert response.get_json()["items"][0]["address"] == "1 Main St"

    empty = client.get("/api/properties?zip=99999")
    assert empty.status_code == 200
    assert empty.get_json()["total"] == 0
    assert empty.get_json()["items"] == []
    assert empty.get_json()["source"]["record_kind"] == "historical_sale"


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ("min_price=-1", "min_price"),
        ("max_price=NaN", "max_price"),
        ("min_beds=none", "min_beds"),
        ("min_price=400000&max_price=300000", "max_price"),
        ("zip=27703.0", "zip"),
        ("south=35.9&west=-79", "bounds"),
        ("south=36&west=-79&north=35&east=-78", "bounds"),
        ("page=0", "page"),
        ("page_size=101", "page_size"),
        ("page=1&page=2", "page"),
        ("unknown=1", "unknown"),
    ],
)
def test_invalid_filters_return_structured_errors(
    tmp_path: Path, query: str, field: str
) -> None:
    response = _app(tmp_path).test_client().get("/api/properties?" + query)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_query"
    assert response.get_json()["error"]["field"] == field


def test_missing_or_incompatible_catalog_is_explicit_while_health_works(
    tmp_path: Path,
) -> None:
    database = tmp_path / "absent.sqlite3"
    client = create_app(
        {"TESTING": True, "PROPERTY_CATALOG_PATH": database}
    ).test_client()
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/properties").status_code == 503
    assert not database.exists()

    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE incompatible (id TEXT)")
    response = client.get("/api/properties/not-present")
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "catalog_unavailable"
