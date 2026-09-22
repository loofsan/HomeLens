"""HomeLens Flask application."""

from collections.abc import Mapping
from typing import Any

from flask import Flask

from homelens.api.health import health_bp


def create_app(test_config: Mapping[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    if test_config is not None:
        app.config.update(test_config)

    app.register_blueprint(health_bp)
    return app
