import json
from pathlib import Path

import pytest
from homelens.data.police_beats import audit_police_beats


def _polygon(west: float, south: float, east: float, north: float) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]
        ],
    }


def _write_beats(path: Path, features: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )


def _feature(code: object, geometry: dict[str, object]) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {"LAWBEAT": code},
        "geometry": geometry,
    }


def test_audits_split_codes_and_unmatched_crime_beats(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_beats(
        raw_dir / "durham_police_beats.geojson",
        [
            _feature(111, _polygon(-79.2, 35.8, -79.1, 35.9)),
            _feature(111, _polygon(-79.1, 35.8, -79.0, 35.9)),
            _feature(112, _polygon(-79.0, 35.8, -78.9, 35.9)),
        ],
    )
    (raw_dir / "DPD_Crime_(table_only).csv").write_text(
        "OBJECTID,BEAT\n1,111\n2,111\n3,112\n4,SSA\n5,\n", encoding="utf-8"
    )

    report = audit_police_beats(raw_dir)

    assert report["beat_geometry"]["features"] == 3
    assert report["beat_geometry"]["unique_codes"] == 2
    assert report["beat_geometry"]["codes_with_multiple_features"] == {"111": 2}
    assert report["beat_geometry"]["same_beat_feature_pairs"] == 0
    assert report["beat_geometry"]["different_beat_feature_pairs"] == 0
    assert (
        report["beat_geometry"][
            "largest_different_beat_overlap_fraction_of_smaller_feature"
        ]
        == 0
    )
    assert report["crime_beat_join"] == {
        "rows": 5,
        "matched_rows": 3,
        "missing_beat_rows": 1,
        "unmatched_nonblank_rows": 1,
        "unmatched_by_code": {"SSA": 1},
        "crime_codes_without_geometry": ["SSA"],
        "geometry_codes_without_crime": [],
    }
    assert report["historical_boundary_alignment"] == "unverified"
    assert len(report["beat_source"]["sha256"]) == 64


def test_reports_positive_area_overlap_between_beats(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_beats(
        raw_dir / "durham_police_beats.geojson",
        [
            _feature(111, _polygon(-79.2, 35.8, -79.0, 36.0)),
            _feature(112, _polygon(-79.1, 35.9, -78.9, 36.1)),
        ],
    )
    (raw_dir / "DPD_Crime_(table_only).csv").write_text(
        "BEAT\n111\n112\n", encoding="utf-8"
    )

    report = audit_police_beats(raw_dir)

    assert report["beat_geometry"]["different_beat_feature_pairs"] == 1
    assert report["beat_geometry"][
        "largest_different_beat_overlap_fraction_of_smaller_feature"
    ] == pytest.approx(0.25)
    assert report["beat_geometry"]["different_beat_code_pairs"] == [["111", "112"]]


def test_accepts_multipart_beat_feature(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_beats(
        raw_dir / "durham_police_beats.geojson",
        [
            _feature(
                111,
                {
                    "type": "MultiPolygon",
                    "coordinates": [
                        _polygon(-79.2, 35.8, -79.1, 35.9)["coordinates"],
                        _polygon(-79.0, 35.8, -78.9, 35.9)["coordinates"],
                    ],
                },
            )
        ],
    )
    (raw_dir / "DPD_Crime_(table_only).csv").write_text("BEAT\n111\n", encoding="utf-8")

    report = audit_police_beats(raw_dir)

    assert report["beat_geometry"]["multipolygon_features"] == 1
    assert report["crime_beat_join"]["matched_rows"] == 1


@pytest.mark.parametrize(
    "geometry,error",
    [
        ({"type": "Point", "coordinates": [-79.0, 36.0]}, "valid polygon"),
        (_polygon(2000000, 800000, 2100000, 900000), "WGS84 lon/lat"),
    ],
)
def test_rejects_nonpolygon_or_projected_geometry(
    tmp_path: Path, geometry: dict[str, object], error: str
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_beats(raw_dir / "durham_police_beats.geojson", [_feature(111, geometry)])

    with pytest.raises(ValueError, match=error):
        audit_police_beats(raw_dir)


def test_rejects_layer_metadata_instead_of_features(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "durham_police_beats.geojson").write_text(
        json.dumps({"type": "Feature Layer", "geometryType": "esriGeometryPolygon"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="FeatureCollection"):
        audit_police_beats(raw_dir)
