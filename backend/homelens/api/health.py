"""Process liveness endpoint."""

from flask import Blueprint

health_bp = Blueprint("health", __name__)


@health_bp.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
