"""Prepare ZCTA demographic profiles from ACS 5-year data profile exports.

Reads data.census.gov CSV downloads of DP05 (demographics) and DP03 (economics)
for ZIP Code Tabulation Areas and writes one aggregate JSON file. Suppressed or
unavailable values stay explicit; nothing is imputed.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from homelens.data.inventory import _file_identity

LABEL_COLUMN = "Label (Grouping)"
MEASURES = ("Estimate", "Margin of Error", "Percent", "Percent Margin of Error")
FILE_PATTERN = re.compile(r"^ACSDP5Y(?P<year>\d{4})\.(?P<table>DP0[35])\b.*\.csv$")
COLUMN_PATTERN = re.compile(
    r"^(?P<geography>.+)!!(?P<measure>" + "|".join(MEASURES) + ")$"
)
ZCTA_PATTERN = re.compile(r"^ZCTA5 (?P<zcta>\d{5})$")

# name: (table, section prefix, indent or None for any, label, reports percent)
METRICS: dict[str, tuple[str, str, int | None, str, bool]] = {
    "total_population": ("DP05", "SEX AND AGE", 4, "Total population", False),
    "median_age_years": ("DP05", "SEX AND AGE", 8, "Median age (years)", False),
    "under_18": ("DP05", "SEX AND AGE", 8, "Under 18 years", True),
    "age_65_and_over": ("DP05", "SEX AND AGE", 8, "65 years and over", True),
    "hispanic_or_latino": (
        "DP05",
        "HISPANIC OR LATINO AND RACE",
        8,
        "Hispanic or Latino (of any race)",
        True,
    ),
    "white_alone_not_hispanic": (
        "DP05",
        "HISPANIC OR LATINO AND RACE",
        12,
        "White alone",
        True,
    ),
    "black_alone_not_hispanic": (
        "DP05",
        "HISPANIC OR LATINO AND RACE",
        12,
        "Black or African American alone",
        True,
    ),
    "american_indian_alone_not_hispanic": (
        "DP05",
        "HISPANIC OR LATINO AND RACE",
        12,
        "American Indian and Alaska Native alone",
        True,
    ),
    "asian_alone_not_hispanic": (
        "DP05",
        "HISPANIC OR LATINO AND RACE",
        12,
        "Asian alone",
        True,
    ),
    "pacific_islander_alone_not_hispanic": (
        "DP05",
        "HISPANIC OR LATINO AND RACE",
        12,
        "Native Hawaiian and Other Pacific Islander alone",
        True,
    ),
    "other_race_alone_not_hispanic": (
        "DP05",
        "HISPANIC OR LATINO AND RACE",
        12,
        "Some Other Race alone",
        True,
    ),
    "two_or_more_races_not_hispanic": (
        "DP05",
        "HISPANIC OR LATINO AND RACE",
        12,
        "Two or More Races",
        True,
    ),
    "median_household_income_usd": (
        "DP03",
        "INCOME AND BENEFITS",
        None,
        "Median household income (dollars)",
        False,
    ),
}
PERCENT_TOKENS = {"", "N", "(X)", "*****", "-", "**", "***"}
UNAVAILABLE_TOKENS = {"", "N", "-", "**", "***", "*****"}


def _measure(raw: str) -> dict[str, Any]:
    """Parse an ACS cell; suppressed, top-coded, and bottom-coded values stay marked."""
    value = raw.strip()
    if value == "(X)":
        return {"value": None, "status": "not_applicable", "source_token": value}
    if value in UNAVAILABLE_TOKENS:
        return {"value": None, "status": "unavailable", "source_token": value}
    status = "available"
    if value.endswith("+"):
        status, value = "top_coded", value[:-1]
    elif len(value) > 1 and value.endswith("-"):
        status, value = "bottom_coded", value[:-1]
    number = value.removeprefix("\N{PLUS-MINUS SIGN}").removesuffix("%")
    number = number.replace(",", "")
    try:
        parsed: int | float = float(number) if "." in number else int(number)
    except ValueError as exc:
        raise ValueError(f"Unexpected ACS value token: {raw!r}") from exc
    result: dict[str, Any] = {"value": parsed, "status": status}
    if status != "available":
        result["source_token"] = raw.strip()
    return result


def _percent_like(raw: str) -> bool:
    value = raw.strip()
    return value.endswith("%") or value in PERCENT_TOKENS


def _exports(raw_dir: Path) -> tuple[str, dict[str, list[Path]]]:
    found: dict[str, dict[str, list[Path]]] = {}
    for path in sorted(raw_dir.glob("ACSDP5Y*.csv")):
        match = FILE_PATTERN.match(path.name)
        if match:
            year_tables = found.setdefault(match["year"], {"DP03": [], "DP05": []})
            year_tables[match["table"]].append(path)
    complete = sorted(
        year for year, tables in found.items() if tables["DP03"] and tables["DP05"]
    )
    if not complete:
        raise ValueError(
            "Expected ACSDP5Y<year>.DP05 and ACSDP5Y<year>.DP03 CSV exports "
            f"for the same year in {raw_dir}"
        )
    year = complete[-1]
    return year, found[year]


def _geographies(header: list[str], name: str) -> dict[str, dict[str, str]]:
    if len(header) != len(set(header)) or not header or header[0] != LABEL_COLUMN:
        raise ValueError(f"{name} is not a data.census.gov data profile export")
    geographies: dict[str, dict[str, str]] = {}
    for column in header[1:]:
        match = COLUMN_PATTERN.match(column)
        if not match:
            raise ValueError(f"{name} has an unexpected column {column!r}")
        geographies.setdefault(match["geography"], {})[match["measure"]] = column
    for geography, columns in geographies.items():
        if set(columns) != set(MEASURES):
            raise ValueError(f"{name} is missing measures for {geography}")
    return geographies


def _geography_key(geography: str) -> str | None:
    match = ZCTA_PATTERN.match(geography)
    if match:
        return match["zcta"]
    if geography == "Durham County, North Carolina":
        return "county"
    return None


def _read_table(path: Path, table: str) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Return {geography key: {metric: matching rows restricted to that geography}}."""
    wanted = {name: spec for name, spec in METRICS.items() if spec[0] == table}
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        header = next(reader, [])
        geographies = _geographies(header, path.name)
        index = {column: position for position, column in enumerate(header)}
        keyed = {
            key: columns
            for geography, columns in geographies.items()
            if (key := _geography_key(geography)) is not None
        }
        selected: dict[str, dict[str, list[dict[str, str]]]] = {
            key: {name: [] for name in wanted} for key in keyed
        }
        section: str | None = None
        for row in reader:
            if len(row) != len(header):
                raise ValueError(f"{path.name} contains an incomplete row")
            raw_label = row[0]
            label = raw_label.strip()
            indent = len(raw_label) - len(raw_label.lstrip())
            if indent == 0 and all(not value.strip() for value in row[1:]):
                section = label
                continue
            for name, (_table, prefix, depth, expected, with_percent) in wanted.items():
                if (
                    section is None
                    or not section.startswith(prefix)
                    or (depth is not None and indent != depth)
                    or label != expected
                ):
                    continue
                for key, columns in keyed.items():
                    values = {
                        measure: row[index[column]]
                        for measure, column in columns.items()
                    }
                    if with_percent and not _percent_like(values["Percent"]):
                        continue
                    selected[key][name].append(values)
    return selected


def _metric(values: dict[str, str], with_percent: bool) -> dict[str, Any]:
    metric = {
        "estimate": _measure(values["Estimate"]),
        "estimate_margin_of_error": _measure(values["Margin of Error"]),
    }
    if with_percent:
        metric["percent"] = _measure(values["Percent"])
        metric["percent_margin_of_error"] = _measure(values["Percent Margin of Error"])
    return metric


def prepare_zcta_profiles(raw_dir: Path) -> dict[str, Any]:
    year, tables = _exports(raw_dir)
    merged: dict[str, dict[str, list[dict[str, str]]]] = {}
    sources = []
    for table in ("DP05", "DP03"):
        for path in tables[table]:
            sources.append({"file": path.name, "identity": _file_identity(path)})
            for key, metrics in _read_table(path, table).items():
                target = merged.setdefault(key, {})
                for name, rows in metrics.items():
                    if target.get(name):
                        raise ValueError(
                            f"{key} appears in more than one {table} export"
                        )
                    target[name] = rows

    profiles: dict[str, Any] = {}
    for key, metrics in sorted(merged.items()):
        missing = [name for name in METRICS if name not in metrics]
        if missing:
            raise ValueError(
                f"{key} is missing {', '.join(missing)}; export DP05 and DP03"
            )
        profile = {}
        for name, rows in metrics.items():
            if len(rows) != 1:
                raise ValueError(
                    f"Expected one {name} row for {key}; found {len(rows)}"
                )
            profile[name] = _metric(rows[0], METRICS[name][4])
        profiles[key] = profile
    zctas = sorted(key for key in profiles if key != "county")
    if not zctas:
        raise ValueError("No ZIP Code Tabulation Area columns were found")
    start = int(year) - 4
    return {
        "dataset": f"{start}-{year} ACS 5-Year Data Profiles DP05 and DP03",
        "vintage": int(year),
        "period": f"{start}-{year}",
        "geography_level": "zcta",
        "zctas": zctas,
        "county_included": "county" in profiles,
        "source_files": sources,
        "profiles": profiles,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare ACS ZCTA demographic profiles"
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/processed/acs_zcta_profiles.json")
    )
    args = parser.parse_args()
    try:
        report = prepare_zcta_profiles(args.raw_dir)
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(report['zctas'])} ZCTA profiles ({report['period']}) "
        f"to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
