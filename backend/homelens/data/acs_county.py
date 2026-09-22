"""Prepare a small, county-only context profile from ACS DP05 exports."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from homelens.data.inventory import _file_identity

GEOGRAPHY = "Durham County, North Carolina"
DATASET = "2023 ACS 1-Year Data Profile DP05"
PATTERN = "ACSDP1Y2023.DP05*.csv"
LABEL_COLUMN = "Label (Grouping)"
MEASURES = (
    "Estimate",
    "Margin of Error",
    "Percent",
    "Percent Margin of Error",
)
METRICS = {
    "total_population": ("SEX AND AGE", 4, "Total population", False),
    "median_age_years": ("SEX AND AGE", 8, "Median age (years)", False),
    "under_18": ("SEX AND AGE", 8, "Under 18 years", True),
    "age_65_and_over": ("SEX AND AGE", 8, "65 years and over", True),
    "total_housing_units": (None, 0, "Total housing units", False),
}


def _headers() -> dict[str, str]:
    return {measure: f"{GEOGRAPHY}!!{measure}" for measure in MEASURES}


def _durham_export(raw_dir: Path) -> Path:
    required = {LABEL_COLUMN, *_headers().values()}
    matches = []
    for path in sorted(raw_dir.glob(PATTERN)):
        with path.open(encoding="utf-8-sig", newline="") as source:
            header = next(csv.reader(source), [])
        if required.issubset(header):
            if len(header) != len(set(header)):
                raise ValueError(f"{path.name} contains duplicate DP05 columns")
            matches.append(path)
    if len(matches) != 1:
        raise ValueError(
            f"Expected one Durham County DP05 export; found {len(matches)}"
        )
    return matches[0]


def _measure(raw: str) -> dict[str, Any]:
    value = raw.strip()
    if value == "(X)":
        return {"value": None, "status": "not_applicable", "source_token": value}
    if value in {"", "N", "*****"}:
        return {"value": None, "status": "unavailable", "source_token": value}
    number = value.removeprefix("\N{PLUS-MINUS SIGN}").removesuffix("%")
    number = number.replace(",", "")
    try:
        parsed = float(number) if "." in number else int(number)
    except ValueError as exc:
        raise ValueError(f"Unexpected DP05 measure token: {value!r}") from exc
    return {"value": parsed, "status": "available"}


def _percent_or_unavailable(raw: str) -> bool:
    value = raw.strip()
    return value.endswith("%") or value in {"", "N", "(X)", "*****"}


def prepare_county_context(raw_dir: Path) -> dict[str, Any]:
    path = _durham_export(raw_dir)
    columns = _headers()
    selected: dict[str, list[dict[str, str]]] = {name: [] for name in METRICS}
    section: str | None = None
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        for row in reader:
            raw_label = row.get(LABEL_COLUMN)
            if raw_label is None or any(
                row.get(column) is None for column in columns.values()
            ):
                raise ValueError(f"{path.name} contains an incomplete DP05 row")
            label = raw_label.strip()
            indent = len(raw_label) - len(raw_label.lstrip())
            if indent == 0 and all(
                not row[column].strip() for column in columns.values()
            ):
                section = label
            for name, (
                expected_section,
                depth,
                expected_label,
                with_percent,
            ) in METRICS.items():
                if (
                    (expected_section is None or section == expected_section)
                    and indent == depth
                    and label == expected_label
                    and (
                        not with_percent
                        or _percent_or_unavailable(row[columns["Percent"]])
                    )
                ):
                    selected[name].append(row)

    metrics: dict[str, Any] = {}
    for name, rows in selected.items():
        if len(rows) != 1:
            raise ValueError(
                f"Expected one {name} row in {path.name}; found {len(rows)}"
            )
        row = rows[0]
        include_percent = METRICS[name][3]
        metrics[name] = {
            "estimate": _measure(row[columns["Estimate"]]),
            "estimate_margin_of_error": _measure(row[columns["Margin of Error"]]),
        }
        if include_percent:
            metrics[name]["percent"] = _measure(row[columns["Percent"]])
            metrics[name]["percent_margin_of_error"] = _measure(
                row[columns["Percent Margin of Error"]]
            )
    return {
        "dataset": DATASET,
        "geography": GEOGRAPHY,
        "geography_level": "county",
        "source_file": path.name,
        "source_identity": _file_identity(path),
        "metrics": metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare Durham County ACS DP05 context"
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/processed/acs_county_context.json")
    )
    args = parser.parse_args()
    try:
        report = prepare_county_context(args.raw_dir)
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote Durham County ACS context to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
