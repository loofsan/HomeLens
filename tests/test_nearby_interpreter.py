"""Free-text nearby requests resolve only to allow-listed categories."""

from __future__ import annotations

from typing import Any

import pytest
from homelens import create_app
from homelens.adapters import openai_search
from homelens.adapters.openai_search import OpenAINearbyProvider, SearchProviderError
from homelens.domain.nearby_intent import NearbyIntent
from homelens.services.nearby_interpreter import NearbyInterpreter


class FakeProvider:
    def __init__(self, category: str | None) -> None:
        self.category = category
        self.calls: list[str] = []

    def interpret_nearby(self, query: str) -> NearbyIntent:
        self.calls.append(query)
        return NearbyIntent(category=self.category)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("query", "category"),
    [
        ("elementary schools", "schools"),
        ("a good daycare", "childcare"),
        ("dog parks", "parks"),
        ("coffee shops", "restaurants"),
        ("Libraries", "libraries"),
        ("gyms nearby", "fitness"),
        ("bus stations", "transit"),
    ],
)
def test_keywords_match_without_a_provider_call(query: str, category: str) -> None:
    provider = FakeProvider("bars")
    result = NearbyInterpreter(provider).interpret(query)
    assert result == {"status": "matched", "category": category, "method": "keyword"}
    assert provider.calls == []


def test_multiple_keywords_are_ambiguous_not_guessed() -> None:
    result = NearbyInterpreter(FakeProvider("bars")).interpret("bars and restaurants")
    assert result["status"] == "ambiguous"
    assert result["category"] is None
    assert result["options"] == ["restaurants", "bars"]


def test_provider_fallback_and_explicit_no_match() -> None:
    provider = FakeProvider("health")
    assert NearbyInterpreter(provider).interpret(
        "somewhere to fill a prescription"
    ) == {
        "status": "matched",
        "category": "health",
        "method": "ai",
    }
    assert provider.calls == ["somewhere to fill a prescription"]
    assert NearbyInterpreter(FakeProvider(None)).interpret("a barber")["status"] == (
        "no_match"
    )
    assert NearbyInterpreter(None).interpret("a barber") == {
        "status": "no_match",
        "category": None,
        "method": None,
    }
    assert NearbyInterpreter(None).interpret("busy streets")["status"] == "no_match"


def test_schema_rejects_categories_outside_the_allow_list() -> None:
    with pytest.raises(ValueError):
        NearbyIntent(category="casinos")  # type: ignore[arg-type]


def test_api_validates_requests_and_works_without_a_key() -> None:
    client = create_app({"TESTING": True, "OPENAI_API_KEY": None}).test_client()
    ok = client.post("/api/nearby/interpret", json={"query": "playground"})
    assert ok.status_code == 200
    assert ok.get_json()["category"] == "parks"
    assert ok.headers["Cache-Control"] == "no-store"
    assert (
        client.post("/api/nearby/interpret", json={"query": "a barber"}).get_json()[
            "status"
        ]
        == "no_match"
    )
    for body in ({"query": "x"}, {"query": "x" * 81}, {"query": 5}, {"q": "park"}):
        assert client.post("/api/nearby/interpret", json=body).status_code == 400
    assert client.post("/api/nearby/interpret", data="park").status_code == 400


def test_openai_nearby_adapter_uses_schema_without_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeResponses:
        def parse(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return type(
                "Response",
                (),
                {
                    "status": "completed",
                    "output_parsed": NearbyIntent(category="parks"),
                },
            )()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(openai_search, "OpenAI", lambda **_kwargs: FakeClient())
    result = OpenAINearbyProvider("test-key", "gpt-4o-mini").interpret_nearby("trails")
    assert result.category == "parks"
    assert captured["store"] is False
    assert captured["text_format"] is NearbyIntent

    class FailingResponses:
        def parse(self, **kwargs: Any) -> Any:
            return type(
                "Response", (), {"status": "incomplete", "output_parsed": None}
            )()

    class FailingClient:
        responses = FailingResponses()

    monkeypatch.setattr(openai_search, "OpenAI", lambda **_kwargs: FailingClient())
    with pytest.raises(SearchProviderError):
        OpenAINearbyProvider("test-key", "gpt-4o-mini").interpret_nearby("trails")
