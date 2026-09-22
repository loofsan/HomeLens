from homelens import create_app


def test_health_returns_ok() -> None:
    app = create_app({"TESTING": True})

    response = app.test_client().get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_app_factory_keeps_configuration_per_instance() -> None:
    first = create_app({"TESTING": True})
    second = create_app()

    assert first.config["TESTING"] is True
    assert second.config["TESTING"] is False
