import json
from pathlib import Path
from typing import Any

import pytest
from homelens import create_app
from homelens.adapters import openai_search
from homelens.adapters.openai_search import OpenAISearchProvider, SearchProviderError
from homelens.domain.search_intent import SearchIntent, SuggestedFilters
from homelens.services.conversational_search import ConversationalSearchService
from homelens.services.search_evaluation import evaluate_cases

CASES = json.loads(
    (Path(__file__).parent / "fixtures/search_intent_cases.json").read_text(
        encoding="utf-8"
    )
)


def _filters(values: dict[str, Any]) -> SuggestedFilters:
    return SuggestedFilters(
        min_price=values.get("min_price"),
        max_price=values.get("max_price"),
        min_beds=values.get("min_beds"),
        min_baths=values.get("min_baths"),
        zip=values.get("zip"),
    )


class FixtureProvider:
    def interpret(
        self, query: str, question: str | None, answer: str | None
    ) -> SearchIntent:
        case = next(case for case in CASES if case["query"] == query)
        return SearchIntent(
            status=case["status"],
            filters=_filters(case["filters"]),
            question="Which exact price range?"
            if case["status"] == "clarify"
            else None,
            unsupported=["unavailable condition"]
            if case["status"] == "unsupported"
            else [],
        )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_regression_cases_produce_only_supported_decisions(
    case: dict[str, Any],
) -> None:
    service = ConversationalSearchService(FixtureProvider())
    result = service.interpret(case["query"])
    assert result["status"] == case["status"]
    assert result["filters"] == case["filters"]
    if case["status"] == "clarify":
        assert result["question"]
    else:
        assert result["question"] is None


def test_api_validates_request_and_manual_search_does_not_require_ai() -> None:
    app = create_app({"TESTING": True, "OPENAI_API_KEY": None})
    client = app.test_client()
    assert "property_search" in app.extensions
    assert (
        client.post("/api/search/interpret", json={"query": "3 beds"}).status_code
        == 503
    )
    assert client.post("/api/search/interpret", json={"query": "x"}).status_code == 400
    assert (
        client.post(
            "/api/search/interpret", json={"query": "3 beds", "sql": "x"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/search/interpret", json={"query": "3 beds", "answer": "4"}
        ).status_code
        == 400
    )
    assert client.post("/api/search/interpret", data="not json").status_code == 400
    assert (
        client.post("/api/search/interpret", json={"query": "x" * 5000}).status_code
        == 413
    )
    assert client.get("/api/health").status_code == 200


def test_api_returns_validated_filter_preview_without_querying_catalog() -> None:
    app = create_app({"TESTING": True, "OPENAI_API_KEY": None})
    app.extensions["conversational_search"] = ConversationalSearchService(
        FixtureProvider()
    )
    response = app.test_client().post(
        "/api/search/interpret", json={"query": CASES[0]["query"]}
    )
    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ready",
        "filters": {"max_price": 400000, "min_beds": 3.0, "zip": "27703"},
        "question": None,
        "message": None,
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_conflicting_or_partially_unsupported_model_output_fails_closed() -> None:
    class ConflictingProvider:
        def interpret(
            self, query: str, question: str | None, answer: str | None
        ) -> SearchIntent:
            return SearchIntent(
                status="ready",
                filters=_filters({"min_price": 600000, "max_price": 300000}),
                question=None,
                unsupported=[],
            )

    class PartialProvider:
        def interpret(
            self, query: str, question: str | None, answer: str | None
        ) -> SearchIntent:
            return SearchIntent(
                status="ready",
                filters=_filters({"max_price": 400000}),
                question=None,
                unsupported=["schools"],
            )

    assert (
        ConversationalSearchService(ConflictingProvider()).interpret("find sales")[
            "status"
        ]
        == "clarify"
    )
    partial = ConversationalSearchService(PartialProvider()).interpret("find sales")
    assert partial["status"] == "unsupported"
    assert partial["filters"] == {}

    class ContradictoryProvider:
        def interpret(
            self, query: str, question: str | None, answer: str | None
        ) -> SearchIntent:
            return SearchIntent(
                status="ready",
                filters=_filters({"min_beds": 3}),
                question="What ZIP?",
                unsupported=[],
            )

    contradictory = ConversationalSearchService(ContradictoryProvider()).interpret(
        "find sales"
    )
    assert contradictory["status"] == "clarify"
    assert contradictory["filters"] == {}


def test_schema_rejects_extra_fields_and_invalid_values() -> None:
    with pytest.raises(ValueError):
        SuggestedFilters.model_validate(
            {**_filters({"zip": "27703"}).model_dump(), "sql": "DROP TABLE sales"}
        )
    with pytest.raises(ValueError):
        _filters({"zip": "2770"})
    with pytest.raises(ValueError):
        _filters({"max_price": -1})


def test_openai_adapter_uses_structured_output_without_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = SearchIntent(
        status="ready",
        filters=_filters({"min_beds": 3}),
        question=None,
        unsupported=[],
    )
    calls: list[dict[str, Any]] = []

    class FakeResponses:
        def parse(self, **kwargs: Any) -> Any:
            calls.append(kwargs)
            return type(
                "Response", (), {"status": "completed", "output_parsed": expected}
            )()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(openai_search, "OpenAI", lambda **_kwargs: FakeClient())
    provider = OpenAISearchProvider("test-key", "gpt-4o-mini")
    assert provider.interpret("3 beds in Durham", None, None) == expected
    assert calls[0]["text_format"] is SearchIntent
    assert calls[0]["store"] is False
    assert calls[0]["max_output_tokens"] <= 350
    assert "3 beds in Durham" in calls[0]["input"][1]["content"]


def test_openai_adapter_refuses_incomplete_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponses:
        def parse(self, **kwargs: Any) -> Any:
            return type(
                "Response", (), {"status": "incomplete", "output_parsed": None}
            )()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(openai_search, "OpenAI", lambda **_kwargs: FakeClient())
    with pytest.raises(SearchProviderError):
        OpenAISearchProvider("test-key", "gpt-4o-mini").interpret("3 beds", None, None)


def test_offline_evaluator_records_aggregate_statuses_and_case_ids() -> None:
    report = evaluate_cases(ConversationalSearchService(FixtureProvider()), CASES)
    assert report["passed"] == 13
    assert report["by_expected_status"]["unsupported"] == {"passed": 7, "total": 7}
    changed = [*CASES]
    changed[0] = {**changed[0], "filters": {"max_price": 1}}
    failed = evaluate_cases(ConversationalSearchService(FixtureProvider()), changed)
    assert failed["passed"] == 12
    assert failed["failures"] == [{"id": "price_beds_zip", "expected_status": "ready"}]
