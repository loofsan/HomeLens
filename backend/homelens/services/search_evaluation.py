"""Offline regression runner for the optional conversational search adapter."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from homelens.adapters.openai_search import OpenAISearchProvider, SearchProviderError
from homelens.services.conversational_search import ConversationalSearchService


def evaluate_cases(
    service: ConversationalSearchService, cases: list[dict[str, Any]]
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    by_status: dict[str, dict[str, int]] = {}
    for case in cases:
        expected_status = str(case["status"])
        summary = by_status.setdefault(expected_status, {"passed": 0, "total": 0})
        summary["total"] += 1
        try:
            result = service.interpret(case["query"])
            matched = (
                result["status"] == expected_status
                and result["filters"] == case["filters"]
            )
        except (SearchProviderError, ValueError):
            matched = False
        if matched:
            summary["passed"] += 1
        else:
            failures.append({"id": str(case["id"]), "expected_status": expected_status})
    return {
        "cases": len(cases),
        "passed": len(cases) - len(failures),
        "by_expected_status": by_status,
        "failures": failures,
        "note": "Offline intent regression; no live catalog or property facts tested.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate AI search intent regression")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("tests/fixtures/search_intent_cases.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/search_intent_evaluation.json"),
    )
    args = parser.parse_args()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        parser.error("OPENAI_API_KEY is required for a live evaluation")
    try:
        cases = json.loads(args.cases.read_text(encoding="utf-8"))
        if not isinstance(cases, list):
            raise ValueError("cases must be an array")
        service = ConversationalSearchService(
            OpenAISearchProvider(
                key, os.environ.get("OPENAI_SEARCH_MODEL", "gpt-4o-mini")
            )
        )
        report = evaluate_cases(service, cases)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"{report['passed']}/{report['cases']} intent cases passed; {args.output}")
    return 0 if report["passed"] == report["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
