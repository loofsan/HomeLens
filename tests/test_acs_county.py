import csv
from pathlib import Path

import pytest
from homelens.data.acs_county import prepare_county_context


def _write_export(
    path: Path,
    geography: str,
    under_18: str = "65,121",
    under_18_percent: str = "19.3%",
    duplicate_header: bool = False,
) -> None:
    header = [
        "Label (Grouping)",
        f"{geography}!!Estimate",
        f"{geography}!!Margin of Error",
        f"{geography}!!Percent",
        f"{geography}!!Percent Margin of Error",
    ]
    space = "\u00a0"
    rows = [
        ["SEX AND AGE", "", "", "", ""],
        [space * 4 + "Total population", "336,892", "*****", "336,892", "(X)"],
        [
            space * 8 + "Median age (years)",
            "36.0",
            "\N{PLUS-MINUS SIGN}0.4",
            "(X)",
            "(X)",
        ],
        [
            space * 8 + "Under 18 years",
            under_18,
            "\N{PLUS-MINUS SIGN}5",
            under_18_percent,
            "\N{PLUS-MINUS SIGN}0.1",
        ],
        [
            space * 8 + "65 years and over",
            "49,889",
            "\N{PLUS-MINUS SIGN}1,061",
            "14.8%",
            "\N{PLUS-MINUS SIGN}0.3",
        ],
        [
            space * 8 + "65 years and over",
            "49,889",
            "\N{PLUS-MINUS SIGN}1,061",
            "49,889",
            "(X)",
        ],
        ["Total housing units", "156,874", "\N{PLUS-MINUS SIGN}246", "(X)", "(X)"],
    ]
    if duplicate_header:
        header.append(header[-1])
        for row in rows:
            row.append(row[-1])
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(header)
        writer.writerows(rows)


def test_prepares_county_only_profile_and_preserves_moe_status(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_export(raw_dir / "ACSDP1Y2023.DP05-national.csv", "United States")
    _write_export(
        raw_dir / "ACSDP1Y2023.DP05-durham.csv", "Durham County, North Carolina"
    )

    report = prepare_county_context(raw_dir)

    assert report["geography"] == "Durham County, North Carolina"
    assert report["geography_level"] == "county"
    assert report["source_file"] == "ACSDP1Y2023.DP05-durham.csv"
    assert len(report["source_identity"]["sha256"]) == 64
    assert report["metrics"]["total_population"]["estimate"]["value"] == 336892
    assert report["metrics"]["total_population"]["estimate_margin_of_error"] == {
        "value": None,
        "status": "unavailable",
        "source_token": "*****",
    }
    assert report["metrics"]["median_age_years"]["estimate"]["value"] == 36.0
    assert (
        report["metrics"]["median_age_years"]["estimate_margin_of_error"]["value"]
        == 0.4
    )
    assert report["metrics"]["under_18"]["percent"]["value"] == 19.3
    assert report["metrics"]["age_65_and_over"]["percent"]["value"] == 14.8
    assert report["metrics"]["total_housing_units"]["estimate"]["value"] == 156874


def test_rejects_missing_or_ambiguous_durham_export(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_export(raw_dir / "ACSDP1Y2023.DP05-national.csv", "United States")
    with pytest.raises(
        ValueError, match="Expected one Durham County DP05 export; found 0"
    ):
        prepare_county_context(raw_dir)

    _write_export(
        raw_dir / "ACSDP1Y2023.DP05-durham-a.csv", "Durham County, North Carolina"
    )
    _write_export(
        raw_dir / "ACSDP1Y2023.DP05-durham-b.csv", "Durham County, North Carolina"
    )
    with pytest.raises(
        ValueError, match="Expected one Durham County DP05 export; found 2"
    ):
        prepare_county_context(raw_dir)


def test_unavailable_measure_is_not_silently_zero(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_export(
        raw_dir / "ACSDP1Y2023.DP05-durham.csv",
        "Durham County, North Carolina",
        under_18="N",
    )

    report = prepare_county_context(raw_dir)

    assert report["metrics"]["under_18"]["estimate"] == {
        "value": None,
        "status": "unavailable",
        "source_token": "N",
    }


def test_unavailable_percent_is_preserved(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_export(
        raw_dir / "ACSDP1Y2023.DP05-durham.csv",
        "Durham County, North Carolina",
        under_18_percent="N",
    )

    report = prepare_county_context(raw_dir)

    assert report["metrics"]["under_18"]["percent"] == {
        "value": None,
        "status": "unavailable",
        "source_token": "N",
    }


def test_duplicate_durham_header_is_rejected(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_export(
        raw_dir / "ACSDP1Y2023.DP05-durham.csv",
        "Durham County, North Carolina",
        duplicate_header=True,
    )

    with pytest.raises(ValueError, match="duplicate DP05 columns"):
        prepare_county_context(raw_dir)
