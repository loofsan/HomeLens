"""HomeLens Flask application."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flask import Flask

from homelens.adapters.google_maps import GoogleContextProvider
from homelens.adapters.openai_search import OpenAISearchProvider
from homelens.api.context import context_bp
from homelens.api.conversational_search import conversational_search_bp
from homelens.api.health import health_bp
from homelens.api.properties import properties_bp
from homelens.data.property_repository import SqlitePropertyRepository
from homelens.services.conversational_search import ConversationalSearchService
from homelens.services.property_context import PropertyContextService
from homelens.services.property_search import PropertySearchService


def create_app(test_config: Mapping[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.setdefault(
        "PROPERTY_CATALOG_PATH",
        os.environ.get(
            "PROPERTY_CATALOG_PATH", "data/processed/property_catalog.sqlite3"
        ),
    )
    app.config.setdefault("GOOGLE_MAPS_API_KEY", os.environ.get("GOOGLE_MAPS_API_KEY"))
    app.config.setdefault("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY"))
    app.config.setdefault(
        "OPENAI_SEARCH_MODEL", os.environ.get("OPENAI_SEARCH_MODEL", "gpt-4o-mini")
    )
    if test_config is not None:
        app.config.update(test_config)

    repository = SqlitePropertyRepository(Path(app.config["PROPERTY_CATALOG_PATH"]))
    app.extensions["property_search"] = PropertySearchService(repository)
    app.extensions["property_context"] = PropertyContextService(
        repository, GoogleContextProvider(app.config["GOOGLE_MAPS_API_KEY"])
    )
    api_key = app.config["OPENAI_API_KEY"]
    app.extensions["conversational_search"] = ConversationalSearchService(
        OpenAISearchProvider(api_key, app.config["OPENAI_SEARCH_MODEL"])
        if api_key
        else None
    )
    app.register_blueprint(health_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(context_bp)
    app.register_blueprint(conversational_search_bp)
    return app
