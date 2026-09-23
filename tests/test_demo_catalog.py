import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from homelens import create_app
from homelens.data.demo_catalog import build_demo_catalog, main
from homelens.data.property_catalog import write_catalog
from homelens.data.property_repository import SqlitePropertyRepository
from homelens.domain.property import PropertyQuery


def test_demo_catalog_has_stable_fictional_records_and_separate_provenance(
    tmp_path: Path,
) -> None:
    records, report = build_demo_catalog()
    repeated, repeated_report = build_demo_catalog()
    assert records == repeated
    assert report == repeated_report
    assert len(records) == 24
    assert len({record.id for record in records}) == 24
    assert all(record.address.startswith("Fictional example ") for record in records)
    assert all(record.source_url is None for record in records)
    assert all(record.city == "Durham" for record in records)
    assert report["synthetic"] is True

    database = tmp_path / "demo_catalog.sqlite3"
    write_catalog(database, records, report)
    page = SqlitePropertyRepository(database).search(PropertyQuery(zip="27703"))
    assert page.source.synthetic is True
    assert page.source.name == "Synthetic HomeLens demo records"
    assert page.source.active_listings is False
    assert page.total == 4
    assert all(record.zip == "27703" for record in page.items)


def test_demo_api_labels_examples_and_never_calls_provider_or_model(
    tmp_path: Path,
) -> None:
    records, report = build_demo_catalog()
    database = tmp_path / "demo_catalog.sqlite3"
    write_catalog(database, records, report)
    app = create_app(
        {
            "TESTING": True,
            "PROPERTY_CATALOG_PATH": database,
            "GOOGLE_MAPS_API_KEY": "local-test-key",
            "VALUATION_ARTIFACT_PATH": tmp_path / "missing-artifact",
        }
    )
    client = app.test_client()
    search = client.get("/api/properties?min_beds=4&page_size=5")
    assert search.status_code == 200
    assert search.json["source"]["synthetic"] is True
    assert search.json["total"] > 0
    sale_id = search.json["items"][0]["id"]
    detail = client.get(f"/api/properties/{sale_id}")
    assert detail.status_code == 200
    assert detail.json["source"]["synthetic"] is True
    assert "not a recorded transaction" in detail.json["description"]

    provider = app.extensions["property_context"]._provider
    with (
        patch.object(provider, "nearby", side_effect=AssertionError("provider called")),
        patch.object(
            provider, "street_view", side_effect=AssertionError("provider called")
        ),
        patch.object(provider, "solar", side_effect=AssertionError("provider called")),
        patch.object(
            provider, "street_view_image", side_effect=AssertionError("provider called")
        ),
    ):
        context = client.get(f"/api/properties/{sale_id}/context")
        assert context.status_code == 200
        for name in ("nearby_places", "street_view", "solar"):
            assert context.json[name]["status"] == "unavailable"
            assert context.json[name]["reason"] == "synthetic_demo"
        image = client.get(f"/api/properties/{sale_id}/street-view/image")
        assert image.status_code == 422
        assert image.json["error"]["code"] == "synthetic_demo"

    valuation = client.get(f"/api/properties/{sale_id}/valuation")
    assert valuation.status_code == 422
    assert (
        valuation.json["error"]["message"] == "Synthetic demo records cannot be valued."
    )


def test_demo_command_refuses_real_name_and_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_path = tmp_path / "property_catalog.sqlite3"
    monkeypatch.setattr(sys, "argv", ["demo_catalog", "--database", str(real_path)])
    with pytest.raises(SystemExit) as blocked:
        main()
    assert blocked.value.code == 2
    assert not real_path.exists()

    demo_path = tmp_path / "demo_catalog.sqlite3"
    monkeypatch.setattr(sys, "argv", ["demo_catalog", "--database", str(demo_path)])
    assert main() == 0
    original = demo_path.read_bytes()
    with pytest.raises(SystemExit) as existing:
        main()
    assert existing.value.code == 2
    assert demo_path.read_bytes() == original
