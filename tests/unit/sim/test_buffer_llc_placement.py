"""Buffer placement (LLC) reaches the DMA transfer specs the BW/power model uses."""
from __future__ import annotations

from types import SimpleNamespace

from scenario_db.sim.transfers import history_port_transfers


def _graph(placement: dict | None, override: dict | None = None) -> SimpleNamespace:
    buf = {"size_ref": "l0", "format": "Y", "bitdepth": 12, "compression": "COMP_YUV_LOSSLESS",
           "history": {"node_id": "mtnr", "frame_offset": -1, "read_ports": ["MTNR0_RDMA_PREV_L0_Y"], "write_ports": ["MTNR0_WDMA_PREV_L0_Y"]}}
    if placement is not None:
        buf["placement"] = placement
    return SimpleNamespace(
        scenario=SimpleNamespace(pipeline={"buffers": {"TNR_PREV_L0": buf}}, size_profile={"anchors": {"l0": "4000x2252"}}),
        variant=SimpleNamespace(buffer_overrides={"TNR_PREV_L0": override} if override else {}, size_overrides={}, design_conditions={}, node_configs={}),
    )


WL = {"mtnr": SimpleNamespace(node_id="mtnr", ip_ref="ip-mtnr", hw_name="MTNR")}


def test_llc_placement_sets_llc_on_buffer_transfers():
    specs = history_port_transfers(_graph({"llc_allocated": True, "llc_weight": 0.6}), WL, {"COMP_YUV_LOSSLESS": 1.0})
    assert len(specs) == 2
    assert all(s.llc_enabled and s.llc_weight == 0.6 for s in specs)
    assert all(s.compression == "COMP_YUV_LOSSLESS" for s in specs)


def test_no_placement_keeps_dram_factor_one():
    specs = history_port_transfers(_graph(None), WL)
    assert all(not s.llc_enabled and s.llc_weight == 1.0 for s in specs)


def test_weight_ignored_when_not_allocated_and_override_merges():
    off = history_port_transfers(_graph({"llc_allocated": False, "llc_weight": 0.6}), WL)
    assert all(not s.llc_enabled and s.llc_weight == 1.0 for s in off)
    merged = history_port_transfers(_graph({"llc_allocated": True, "llc_weight": 0.6}, {"placement": {"llc_weight": 0.5}}), WL)
    assert all(s.llc_enabled and s.llc_weight == 0.5 for s in merged)
