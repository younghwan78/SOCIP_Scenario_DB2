from __future__ import annotations

from pathlib import Path

import pytest

from scenario_db.etl.rename_ids import load_map, rewrite

REPO = Path(__file__).resolve().parents[2]


def test_rewrite_replaces_exact_values_and_dict_keys_only():
    mapping = {"uc-camera-recording": "uc-cam-recording-e2600"}
    doc = {
        "scenario_ref": "uc-camera-recording",
        "note": "uc-camera-recording was renamed",          # prose is kept
        "path": "uc-camera-recording/trace.pb",               # source paths are kept
        "per_scenario": {"uc-camera-recording": [1, "uc-camera-recording"]},
    }
    out = rewrite(doc, mapping)
    assert out["scenario_ref"] == "uc-cam-recording-e2600"
    assert out["note"] == doc["note"] and out["path"] == doc["path"]
    assert out["per_scenario"] == {"uc-cam-recording-e2600": [1, "uc-cam-recording-e2600"]}


def test_repository_rename_map_is_one_step_and_covers_every_fixture_scenario():
    mapping = load_map(REPO / "authoring" / "id-renames.yaml")
    assert mapping["uc-camera-recording"] == "uc-cam-recording-e2600"
    assert mapping["proj-e2700-ref"] == "proj-sm-s957b"
    assert all(v.endswith(("-e2600", "-e2700")) for k, v in mapping.items() if k.startswith("uc-"))


def test_load_map_rejects_chained_renames(tmp_path: Path):
    p = tmp_path / "m.yaml"
    p.write_text("renames:\n  a: b\n  b: c\n", encoding="utf-8")
    with pytest.raises(ValueError, match="one-step"):
        load_map(p)
