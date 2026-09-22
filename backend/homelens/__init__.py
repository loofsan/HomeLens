"""HomeLens Flask application."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flask import Flask

from homelens.api.health import health_bp
from homelens.api.properties import properties_bp
from homelens.data.property_repository import SqlitePropertyRepository
from homelens.services.property_search import PropertySearchService


def create_app(test_config: Mapping[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.setdefault(
        "PROPERTY_CATALOG_PATH", "data/processed/property_catalog.sqlite3"
    )
    if test_config is not None:
        app.config.update(test_config)

    app.extensions["property_search"] = PropertySearchService(
        SqlitePropertyRepository(Path(app.config["PROPERTY_CATALOG_PATH"]))
    )
    app.register_blueprint(health_bp)
    app.register_blueprint(properties_bp)
    return app
