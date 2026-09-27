"""Power-saving options (knob values / substitute IP modes) explored on top of a variant."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim import arch_exploration as ax  # noqa: E402
from scenario_db.sim import power_options as po  # noqa: E402
from scenario_db.sim.models import DVFSTable  # noqa: E402

UHD30 = "cam-rec-r1-uhd30-vdis"
MTNR = "ip-mtnr-is-v15-s5e9965"
BCROP = "knob:crop_strategy=byrp_bcrop"
L0SKIP = "knob:pyramid_l0=skip"
MTNR_LP = "mode:mtnr=LowPower"


def _row(d: dict) -> IpCatalog:
    return IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")


@pytest.fixture(scope="module")
def raw():
    return read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml")


@pytest.fixture(scope="module")
def catalog():
    return {d["id"]: _row(d) for d in (read(p) for p in (FIXTURE / "00_hw").glob("ip-*.yaml"))}


@pytest.fixture(scope="module")
def lp_catalog(catalog):
    """MTNR with a declared low-power substitute of Normal (own unit power)."""
    out = dict(catalog)
    d = {"id": MTNR, "schema_version": catalog[MTNR].schema_version, "category": catalog[MTNR].category,
         "hierarchy": catalog[MTNR].hierarchy, "capabilities": deepcopy(catalog[MTNR].capabilities)}
    modes = d["capabilities"]["sim"]["modes"]
    modes["LowPower"] = {**modes["Normal"], "unit_power_mw_mp": 0.6, "substitutes": ["Normal"],
                         "iq_eval": "required", "label": "MTNR low-power NR"}
    modes["HighSpeed"] = {**modes["Normal"], "unit_power_mw_mp": 1.4}  # no substitutes -> never explored
    out[MTNR] = _row(d)
    return out


@pytest.fixture(scope="module")
def dvfs():
    doc = yaml.safe_load((FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml").read_text(encoding="utf-8"))
    return {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}


@pytest.fixture(scope="module")
def uhd30(raw, lp_catalog, dvfs):
    return ax.explore_variant(graph_from_fixture(raw, UHD30, lp_catalog), ax.ArchExplorationSpec(), dvfs_tables=dvfs)


def test_dimensions_come_from_knob_explore_and_mode_substitutes(raw, lp_catalog):
    dims, notes = po.option_dimensions(graph_from_fixture(raw, UHD30, lp_catalog))
    assert {d["id"]: [i["key"] for i in d["items"]] for d in dims} == {
        "knob:crop_strategy": [BCROP], "knob:pyramid_l0": [L0SKIP], "mode:mtnr": [MTNR_LP]}
    lp = next(d for d in dims if d["id"] == "mode:mtnr")["items"][0]
    assert (lp["from"], lp["unit_power_mw_mp"], lp["from_unit_power_mw_mp"]) == ("Normal", 0.6, 1.0)
    assert notes == [] and po.count_sets(dims) == 7


def test_knob_explore_condition_and_adopted_value(raw, catalog):
    psm = po.option_dimensions(graph_from_fixture(raw, "cam-rec-r1-uhd60-psm", catalog))
    assert [d["id"] for d in psm[0]] == ["knob:pyramid_l0"]          # EIS off: no bcrop
    assert any("BYRP bayer crop" in n and "eis" in n for n in psm[1])
    adopted = deepcopy(raw)
    v = next(x for x in adopted["variants"] if x["id"] == UHD30)
    v["design_conditions"]["crop_strategy"] = "byrp_bcrop"
    dims, notes = po.option_dimensions(graph_from_fixture(adopted, UHD30, catalog))
    assert "knob:crop_strategy" not in [d["id"] for d in dims]
    assert any("already selects 'byrp_bcrop'" in n for n in notes)


def test_full_factorial_results_and_attribution(uhd30):
    p = uhd30["power_options"]
    assert p["status"] == "ok" and p["sets"] == 7 and len(p["results"]) == 7 and not p["errors"]
    by = {r["key"]: r for r in p["results"]}
    both = by[f"{BCROP}+{L0SKIP}"]
    rec = uhd30["recommended"]["total_mw"]
    for r in p["results"]:
        assert r["iq_eval"] == "required" and r["spec_ok"]
        assert r["total_mw"] == pytest.approx(rec + r["delta_mw"], abs=0.01)
        # additive attribution of option vs the variant's recommended case
        assert r["attribution"]["delta_mw"] == pytest.approx(r["delta_mw"], abs=0.01)
    assert both["delta_mw"] < by[BCROP]["delta_mw"] < 0 and both["delta_mw"] < by[L0SKIP]["delta_mw"] < 0
    assert by[L0SKIP]["attribution"]["by_category"]["BW traffic"] < 0        # PYRAMID_L0 DMA gone
    assert "IP workload" in by[BCROP]["attribution"]["by_category"]           # smaller RGBP..MCSC frames
    assert set(by[MTNR_LP]["attribution"]["by_category"]) == {"IP workload"}  # unit power only
    assert by[MTNR_LP]["raw_delta_mw"] < 0 and by[MTNR_LP]["kinds"] == ["ip_mode"]
    deltas = [r["delta_mw"] for r in p["results"]]
    assert deltas == sorted(deltas) and p["best"] == p["results"][0]["key"]


def test_cap_and_disable(raw, lp_catalog, dvfs):
    g = graph_from_fixture(raw, UHD30, lp_catalog)
    capped = ax.explore_variant(g, ax.ArchExplorationSpec(axes={"power_options": {"max_sets": 3}}), dvfs_tables=dvfs)
    assert capped["power_options"]["status"] == "skipped" and capped["power_options"]["results"] == []
    assert capped["recommended"] is not None                         # the variant itself is still explored
    off = ax.explore_variant(g, ax.ArchExplorationSpec(axes={"power_options": {"enabled": False}}), dvfs_tables=dvfs)
    assert "power_options" not in off
    knobs_only = ax.explore_variant(g, ax.ArchExplorationSpec(axes={"power_options": {"include_modes": False}}),
                                    dvfs_tables=dvfs)
    assert knobs_only["power_options"]["sets"] == 3


def test_option_sets_change_the_input_hash(raw, catalog, lp_catalog, dvfs):
    spec = ax.ArchExplorationSpec(axes={"power_options": {"enabled": False}})
    a = ax.input_hash(graph_from_fixture(raw, UHD30, catalog), spec, ax.SimulationRunConfig(), dvfs)
    b = ax.input_hash(graph_from_fixture(raw, UHD30, lp_catalog), spec, ax.SimulationRunConfig(), dvfs)
    assert a != b


def test_review_report_lists_option_savings(uhd30):
    from scenario_db.reporting.arch_report import build_snapshot, render_html

    run = {"id": "r", "title": "r", "scenario_type": "camera", "variants": [uhd30], "spec": {}}
    snap = build_snapshot(run, {}, {})
    row = snap["power_options"][0]
    assert row["variant_id"] == UHD30 and row["best"]["key"] == uhd30["power_options"]["best"]
    assert {s["key"] for s in row["singles"]} == {BCROP, L0SKIP, MTNR_LP}
    html = render_html("Report", snap)
    assert "Power option (IQ 평가 대상)" in html and "BYRP bayer crop" in html


def test_knob_spec_read_back_from_jsonb_order(raw, catalog, dvfs):
    """Postgres JSONB sorts object keys; derived anchors must not depend on authored order."""
    shuffled = deepcopy(raw)
    derived = shuffled["power_options"]["knobs"]["crop_strategy"]["values"]["byrp_bcrop"]["derived"]
    shuffled["power_options"]["knobs"]["crop_strategy"]["values"]["byrp_bcrop"]["derived"] = dict(
        sorted(derived.items(), key=lambda kv: (len(kv[0]), kv[0])))
    g = graph_from_fixture(shuffled, UHD30, catalog)
    dims, _ = po.option_dimensions(g)
    items = [i for d in dims for i in d["items"] if i["key"] == BCROP]
    got = po.variant_dict(po.apply_option_set(g, items).variant)["size_overrides"]
    ref = po.variant_dict(po.apply_option_set(graph_from_fixture(raw, UHD30, catalog), items).variant)["size_overrides"]
    assert got == ref and got["bcrop_out"] == got["mlsc_out"] == got["pyramid_l0"]
    r = ax.explore_variant(g, ax.ArchExplorationSpec(), dvfs_tables=dvfs)
    assert r["power_options"]["errors"] == [] and len(r["power_options"]["results"]) == 3
