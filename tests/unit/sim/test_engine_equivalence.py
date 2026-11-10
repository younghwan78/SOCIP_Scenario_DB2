"""The equivalence guard must detect changed, missing and differently encoded results."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_engine_equivalence import (  # noqa: E402
    EXCLUDED_PATHS, VARIANTS, canonical_json, compare, first_difference,
)
from verify_is_v15_camera import FIXTURE, read  # noqa: E402


def test_fixed_variants_cover_every_project_recording_kpi():
    project = read(FIXTURE / "02_definition" / "proj-sm-s947b.yaml")
    kpis = project["globals"]["review_policy"]["kpi"]
    for kpi in kpis:
        scenario = kpi.get("scenario_ref", "uc-cam-recording-e2600")
        assert kpi["variant_ref"] in VARIANTS[scenario]
    assert len(VARIANTS["uc-cam-preview-e2600"]) >= 2
    assert len(VARIANTS["uc-cam-capture-e2600"]) >= 2
    assert "cam-rec-r1-uhd30-vdis" in VARIANTS["uc-cam-recording-e2600"]


def test_canonical_output_retains_all_fields_and_float_precision():
    assert not EXCLUDED_PATHS
    first = canonical_json({"value": 1.2345678901234567, "input_hash": "a"})
    assert first == canonical_json({"input_hash": "a", "value": 1.2345678901234567})
    assert first != canonical_json({"input_hash": "a", "value": 1.2345678901234569})
    assert canonical_json({"value": 1}) != canonical_json({"value": 1.0})


def test_compare_identical_results_ignores_timing_metadata(tmp_path, capsys):
    a, b = tmp_path / "a", tmp_path / "b"
    for root, seconds in ((a, 1), (b, 2)):
        (root / "metadata").mkdir(parents=True)
        (root / "variant.json").write_bytes(canonical_json({"value": 1}).encode())
        (root / "metadata" / "measurements.json").write_bytes(str(seconds).encode())
    assert compare(a, b) == 0
    assert "1 variants: 0 differences" in capsys.readouterr().out


@pytest.mark.parametrize("changed,path", (
    ({"rows": [{"power": 1.01}]}, '$["rows"][0]["power"]'),
    ({"rows": []}, '$["rows"][0]'),
    ({"extra": 1, "rows": [{"power": 1.0}]}, '$["extra"]'),
))
def test_compare_reports_first_changed_path(tmp_path, capsys, changed, path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    baseline = {"rows": [{"power": 1.0}]}
    (a / "variant.json").write_bytes(canonical_json(baseline).encode())
    (b / "variant.json").write_bytes(canonical_json(changed).encode())
    assert compare(a, b) == 1
    assert path in capsys.readouterr().out


def test_compare_rejects_missing_variants_empty_sets_and_changed_bytes(tmp_path, capsys):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert compare(a, b) == 1
    (a / "variant.json").write_bytes(b'{"value": 1}\n')
    (b / "variant.json").write_bytes(b'{"value":1}\n')
    assert compare(a, b) == 1
    assert "JSON bytes differ" in capsys.readouterr().out
    (a / "extra-variant.json").write_bytes(b"{}\n")
    assert compare(a, b) == 1
    assert "missing from b" in capsys.readouterr().out


def test_first_difference_keeps_numeric_types_and_signed_zero():
    assert first_difference(1, 1.0) == "$: type int != float"
    assert first_difference(0.0, -0.0) is not None
