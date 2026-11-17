"""S-08 assumed IP: catalog values overlaid on one node (What-if / exploration lever), declared cores, raised cap."""

from copy import deepcopy

import pytest

from scenario_db.api.schemas.scenario_whatif import WhatIfChange
from scenario_db.api.services.design_axes import EXPLORABLE_KINDS
from scenario_db.api.services.whatif_conditions import CHANGE_KINDS, apply_whatif_changes, whatif_targets
from scenario_db.db.models.definition import Project
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph


@pytest.fixture
def graph():
    g = _exynos2600_generated_graph("uc-cam-recording-e2600", "cam-rec-r1-uhd30-vdis")
    g.project = Project(id=g.scenario.project_ref, metadata_={"soc_ref": "soc-exynos2600"}, globals_={})
    return g


def _workload(graph, node):
    return next(w for w in build_simulation_inputs(graph, SimulationRunConfig()).workloads if w.node_id == node)


def _ip(report, node):
    return next(i for i in report["ips"] if i["node"] == node)


def test_the_lever_is_registered_and_explorable(graph):
    kind = CHANGE_KINDS["ip_param"]
    assert kind.needs_param and kind.selector == "node_id" and "ip_param" in EXPLORABLE_KINDS
    choices = kind.discover(whatif_targets(graph))
    assert {c["param"] for c in choices if c["id"] == "mfc_enc"} == {"ppc", "unit_power_mw_mp", "assume_max_clock_mhz", "cores"}


def test_a_doubled_ppc_halves_the_required_clock_and_leaves_the_loaded_graph(graph):
    node = next(n["id"] for n in whatif_targets(graph)["nodes"] if n["clock_supported"] and n["id"] == "mfc_enc")
    before = _workload(graph, node)
    candidate, config, _ = apply_whatif_changes(
        graph, [WhatIfChange(target="ip_param", node_id=node, param="ppc", value=before.sim_params.ppc * 2)], SimulationRunConfig())
    after = _workload(candidate, node)
    assert after.sim_params.ppc == pytest.approx(before.sim_params.ppc * 2)
    assert "ip_params" not in (graph.variant.node_configs.get(node, {}).get("sim") or {})  # detached copy
    a = analyze_timing_budget(graph, TimingBudgetOptions())
    b = analyze_timing_budget(candidate, TimingBudgetOptions(), config=config)
    assert _ip(b, node)["own_required_mhz"] == pytest.approx(_ip(a, node)["own_required_mhz"] / 2, rel=0.02)


def test_unit_power_and_an_assumed_max_clock_above_the_catalog(graph):
    node = "mfc_enc"
    base = _workload(graph, node)
    cap = base.sim_params.max_clock_mhz
    changes = [WhatIfChange(target="ip_param", node_id=node, param="unit_power_mw_mp", value=1.5),
               WhatIfChange(target="ip_param", node_id=node, param="assume_max_clock_mhz", value=(cap or 600) + 400)]
    candidate, _, _ = apply_whatif_changes(graph, changes, SimulationRunConfig())
    after = _workload(candidate, node)
    assert after.sim_params.unit_power_mw_mp == 1.5
    assert after.sim_params.max_clock_mhz == (cap or 600) + 400  # raised: the assumed IP replaces the cap
    # max_clock_mhz (not assumed) still only lowers a catalog cap, while the assumed value replaces it
    capped = deepcopy(graph)
    capped.variant.node_configs.setdefault(node, {}).setdefault("sim", {})["ip_params"] = {"max_clock_mhz": 300}
    assert _workload(capped, node).sim_params.max_clock_mhz == min(300, cap or 300)
    capped.variant.node_configs[node]["sim"]["ip_params"]["assume_max_clock_mhz"] = 900
    assert _workload(capped, node).sim_params.max_clock_mhz == 900


def test_declared_cores_on_a_node_and_in_the_catalog(graph):
    base = analyze_timing_budget(graph, TimingBudgetOptions())
    assert base["mfc_dual"] == {"mfc_enc": 2}  # the built-in rule (UHD encoder)
    one, config, _ = apply_whatif_changes(graph, [WhatIfChange(target="ip_param", node_id="mfc_enc", param="cores", value=1)],
                                          SimulationRunConfig())
    r1 = analyze_timing_budget(one, TimingBudgetOptions(), config=config)
    assert r1["mfc_dual"] == {}
    assert _ip(r1, "mfc_enc")["own_required_mhz"] == pytest.approx(2 * _ip(base, "mfc_enc")["own_required_mhz"], rel=0.02)
    # a catalog declaration replaces the rule for that IP; mfc_dual=off still turns it off
    cat = deepcopy(graph)
    ip = cat.ip_catalog[_workload(cat, "mfc_enc").ip_ref]
    ip.capabilities = {**ip.capabilities, "sim": {**ip.capabilities["sim"], "multi_core": {"cores": 3, "min_pixels": 0}}}
    assert analyze_timing_budget(cat, TimingBudgetOptions())["mfc_dual"] == {"mfc_enc": 3}
    assert analyze_timing_budget(cat, TimingBudgetOptions(mfc_dual="off"))["mfc_dual"] == {}


@pytest.mark.parametrize("kw,match", [
    ({"param": "gamma", "value": 1}, "unsupported ip_param"),
    ({"param": "cores", "value": 1.5}, "integer"),
    ({"param": "ppc", "value": 65}, "at most"),
])
def test_bad_assumptions_are_refused(graph, kw, match):
    with pytest.raises(ValueError, match=match):
        apply_whatif_changes(graph, [WhatIfChange(target="ip_param", node_id="mfc_enc", **kw)], SimulationRunConfig())


def test_an_assumed_ip_axis_is_explored_like_any_resim_lever():
    # S-08: "what if the encoder had 2x ppc / one core" as exploration axes over the recording fixture
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    from verify_is_v15_camera import FIXTURE, graph_from_fixture, read

    from scenario_db.api.services.design_axes import build_design_plan
    from scenario_db.db.models.capability import IpCatalog
    from scenario_db.sim.arch_exploration import LeverAxis

    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    g = graph_from_fixture(read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml"), "cam-rec-r1-uhd30-vdis", catalog)
    plan = build_design_plan(g, SimulationRunConfig(), [
        LeverAxis(lever="ip_param", params={"node_id": "mfc_enc", "param": "ppc"}, values=[4.0, 8.0]),
        LeverAxis(lever="ip_param", params={"node_id": "mfc_enc", "param": "cores"}, values=[1])])
    sets = {s["key"]: s for s in plan["sets"]}
    assert len(sets) == 5 and not any("error" in s for s in sets.values())
    assert all(s["iq"] == "neutral" for s in sets.values())
