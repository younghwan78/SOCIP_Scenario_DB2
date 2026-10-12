from pathlib import Path

import yaml

from scenario_db.view.memory_levers import memory_levers

REC = Path("db_Exynos2600_SM-S947B/02_definition/uc-cam-recording-e2600.yaml")


def test_e2600_recording_mtnr_levers():
    raw = yaml.safe_load(REC.read_text(encoding="utf-8"))
    lv = memory_levers(raw["pipeline"], {})
    assert set(lv["llc"]) == {"PYRAMID_L0", "PYRAMID_L1", "TNR_PREV_L0", "TNR_PREV_L1"}
    assert set(lv["compressed"]) == {"PYRAMID_L0", "PYRAMID_L1"}
    assert lv["votf"] == [] and lv["llc_weight_min"] == 0.6
    assert lv["llc_mb"] == 4 and lv["llc_owners"] == ["MTNR"] and lv["llc_unsized"] == 0  # one MTNR partition, not 4 x 4MB
    assert lv["compressed_dma"] > 2
    # MTNR off: its history buffers and the MLSC->MTNR pyramid buffers drop out
    assert memory_levers(raw["pipeline"], {}, ["mtnr"])["llc"] == []


def test_overrides_and_votf():
    pipe = {"edges": [{"from": "a", "to": "b", "type": "M2M", "buffer": "B"}, {"from": "b", "to": "c", "type": "vOTF"}],
            "buffers": {"B": {"compression": "COMP_OFF", "placement": {"llc_allocated": True}}}}
    lv = memory_levers(pipe, {"B": {"compression": "COMP_YUV_LOSSY", "placement": {"llc_allocated": False}}})
    assert {k: lv[k] for k in ("llc", "compressed", "votf", "llc_mb", "compressed_dma")} == {
        "llc": [], "compressed": ["B"], "votf": ["b->c"], "llc_mb": None, "compressed_dma": 2}
    assert memory_levers(pipe, {}, ["c"])["votf"] == []
