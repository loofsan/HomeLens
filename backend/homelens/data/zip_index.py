"""Prepare the supplied ZIP-level home value index for index adjustments.

The supplied `zipcode_saleprice.csv` has the layout of a Zillow Research ZIP
download with smooth monthly levels, consistent with a Zillow Home Value Index
(ZHVI) series of unconfirmed variant. It is not observed median sale prices.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any

from homelens.data.inventory import _file_identity

SOURCE_FILE = "zipcode_saleprice.csv"
SERIES_LABEL = "ZHVI-style typical home value index (Zillow Research layout)"
MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID_COLUMNS = ("RegionName", "RegionType")


def _value(raw: str, name: str, month: str) -> float | None:
    text = raw.strip()
    if not text:
        return None
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} {month} has a non-positive index value")
    return round(value, 2)


def prepare_zip_index(raw_dir: Path) -> dict[str, Any]:
    path = raw_dir / SOURCE_FILE
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        header = reader.fieldnames or []
        missing = [column for column in ID_COLUMNS if column not in header]
        if missing:
            raise ValueError(f"{path.name} missing columns: {', '.join(missing)}")
        months = [column for column in header if MONTH_PATTERN.match(column)]
        if not months or months != sorted(months):
            raise ValueError(f"{path.name} needs ordered monthly date columns")
        normalized = [month[:7] for month in months]
        if len(set(normalized)) != len(normalized):
            raise ValueError(f"{path.name} has more than one column per month")
        series: dict[str, list[float | None]] = {}
        for row in reader:
            if row["RegionType"] != "zip":
                continue
            name = row["RegionName"].strip().zfill(5)
            if not re.fullmatch(r"\d{5}", name) or name in series:
                raise ValueError(f"{path.name} has an invalid or repeated ZIP {name}")
            series[name] = [_value(row[month], name, month) for month in months]
    if not series:
        raise ValueError(f"{path.name} has no ZIP rows")
    return {
        "series_label": SERIES_LABEL,
        "series_metric": "typical_home_value_index",
        "variant_confirmed": False,
        "source_file": path.name,
        "source_identity": _file_identity(path),
        "months": normalized,
        "zips": dict(sorted(series.items())),
        "missing_values": {
            name: sum(value is None for value in values)
            for name, values in sorted(series.items())
            if any(value is None for value in values)
        },
        "forecast": None,
        "forecast_note": (
            "No forward projection is served. In the rolling-origin backtest in "
            "notebooks/zip_value_outlook.ipynb, no method beat a no-change "
            "baseline at every 1-5 year horizon on both development and holdout "
            "origins."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the ZIP value index")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/processed/zip_value_index.json")
    )
    args = parser.parse_args()
    try:
        report = prepare_zip_index(args.raw_dir)
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(report['zips'])} ZIP index series "
        f"({report['months'][0]} to {report['months'][-1]}) to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
