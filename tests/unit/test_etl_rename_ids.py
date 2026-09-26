from __future__ import annotations

from pathlib import Path

import pytest

from scenario_db.etl.rename_ids import _canonical_corrupted, load_map, rewrite

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


def test_repository_rename_map_resolves_to_current_ids():
    mapping = load_map(REPO / "authoring" / "id-renames.yaml")
    assert mapping["uc-camera-recording"] == "uc-cam-recording-e2600"
    assert mapping["uc-camera-recording-apv"] == "uc-cam-recording-apv-e2600"
    assert mapping["proj-e2700-ref"] == "proj-sm-s957b"
    # current fixture ids are never renamed (the withdrawn APV merge must not come back)
    assert "uc-cam-recording-apv-e2600" not in mapping
    assert all(v.endswith(("-e2600", "-e2700")) for k, v in mapping.items() if k.startswith("uc-"))


def test_load_map_collapses_chains_and_rejects_cycles(tmp_path: Path):
    p = tmp_path / "m.yaml"
    p.write_text("renames:\n  a: b\n  b: c\n", encoding="utf-8")
    assert load_map(p) == {"a": "c", "b": "c"}
    p.write_text("renames:\n  a: b\n  b: a\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cycle"):
        load_map(p)


def test_rewrite_never_touches_canonical_usecase():
    """Regression: old id 'uc-game-play' equals the canonical key of uc-game-play-e2600."""
    mapping = {"uc-game-play": "uc-game-play-e2600"}
    out = rewrite({"canonical_usecase": "uc-game-play", "scenario_ref": "uc-game-play"}, mapping)
    assert out == {"canonical_usecase": "uc-game-play", "scenario_ref": "uc-game-play-e2600"}


def test_canonical_rewritten_by_an_earlier_rename_is_detected():
    targets = {"uc-game-play-e2600"}
    assert _canonical_corrupted({"metadata": {"canonical_usecase": "uc-game-play-e2600"}}, targets)
    assert not _canonical_corrupted({"metadata": {"canonical_usecase": "uc-game-play"}}, targets)
