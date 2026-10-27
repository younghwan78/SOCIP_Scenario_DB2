"""Commercialization levers (sensor · crop/downscale · power option · history rate · IP mode · SBWC) and combine."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from scenario_db.api.services import analysis_inputs
from scenario_db.api.schemas.scenario_whatif import WhatIfAskRequest, WhatIfChange, WhatIfPreviewRequest, WhatIfScope
from scenario_db.api.services import scenario_whatif as service
from scenario_db.api.services.whatif_levers import _reshape, scaled_size
from scenario_db.db.models.definition import Project
from scenario_db.sim.measured_timing import baseline_fingerprint
from scenario_db.sim.transfers import history_rate
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph, _read_yaml

pytest.importorskip("networkx")

ROOT = "db_Exynos2600_SM-S947B"


def _graph():
    from pathlib import Path
    root = Path(__file__).resolve().parents[3] / ROOT
    g = _exynos2600_generated_graph("uc-cam-recording-e2600", "cam-rec-r1-uhd30-vdis")
    g.project = Project(id=g.scenario.project_ref, metadata_={"soc_ref": "soc-exynos2600"}, globals_={})
    g.scenario.power_options = _read_yaml(root / "02_definition" / "uc-cam-recording-e2600.yaml").get("power_options")
    soc = yaml.safe_load((root / "00_hw" / "soc-exynos2600.yaml").read_text(encoding="utf-8"))
    g.soc = SimpleNamespace(id="soc-exynos2600", compression_modes=soc["compression_modes"], platform_model=None, ips=[])
    return g


@pytest.fixture(scope="module")
def env():
    graph = _graph()
    mp = pytest.MonkeyPatch()
    mp.setattr(analysis_inputs.AnalysisSelection, "load", lambda *a: analysis_inputs.AnalysisInputs(graph, {}, None))
    mp.setattr(analysis_inputs, "_apply_config_profile", lambda *a: None)
    mp.setattr(service, "scenario_policy", lambda *a: None)
    scope = dict(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id, variant_id=graph.variant_id)
    targets = service.targets(MagicMock(), WhatIfScope(**scope))
    yield graph, scope, targets
    mp.undo()


def _preview(env, *changes):
    graph, scope, _ = env
    before = baseline_fingerprint(graph)
    out = service.preview(MagicMock(), WhatIfPreviewRequest(**scope, expected_baseline_hash=before, changes=list(changes)))
    assert baseline_fingerprint(graph) == before, "the loaded graph must stay untouched"
    b, c = out["baseline"]["metrics"], out["candidate"]["metrics"]
    return out, {k: c[k] - b[k] for k in ("modeled_power_mw", "ip_power_mw", "memory_power_mw", "bw_mbs")}


def test_lever_targets_are_discovered_from_variant_data(env):
    _, _, t = env
    kinds = {k["target"]: k for k in t["change_kinds"]}
    for target in ("sensor_mode", "chain_size", "power_knob", "history_interval", "ip_mode", "compression"):
        assert target in kinds and kinds[target]["choices"], target
    assert kinds["sensor_mode"]["group"] == "sensor" and kinds["sensor_mode"]["iq"] == "required"
    sensor = t["sensors"][0]
    assert sensor["node_id"] == "sensor_rear" and sensor["options"][0]["current"]
    assert all(o["fps_compatible"] == (o["fps"] is None or o["fps"] >= 30) for o in sensor["options"])
    assert sensor["truncated"] is False
    assert t["chains"][0]["id"] == "byrp" and "mtnr" in t["chains"][0]["downstream"]
    assert {k["param"] for k in t["knobs"]} == {"crop_strategy", "pyramid_l0"}
    assert {h["id"] for h in t["history"]} >= {"TNR_PREV_L0", "TNR_PREV_L1"}
    l0 = next(b for b in t["buffers"] if b["id"] == "PYRAMID_L0")
    assert l0["current"] == "COMP_YUV_LOSSLESS" and {o["id"] for o in l0["options"]} >= {"COMP_OFF", "COMP_YUV_LOSSY"}


def test_history_interval_halves_previous_frame_traffic(env):
    out, d = _preview(env, {"target": "history_interval", "value": 2})
    assert d["bw_mbs"] < -100 and d["memory_power_mw"] < 0 and d["ip_power_mw"] == pytest.approx(0, abs=1e-6)
    assert "history_interval" in out["iq_required"]
    assert history_rate({"update_interval": 2}) == 0.5 and history_rate({}) == 1.0
    with pytest.raises(ValueError):
        history_rate({"update_interval": 0})


def test_chain_crop_shrinks_downstream_ips_and_pyramid(env):
    out, d = _preview(env, {"target": "chain_size", "node_id": "byrp", "width": 3744, "height": 2112})
    assert d["ip_power_mw"] < 0 and d["bw_mbs"] < 0
    assert any("pyramid_l1" in n for n in out["lever_notes"])
    ips = {ip["node"]: ip for ip in out["candidate"]["report"]["ips"]}
    assert ips["byrp"]["power_mw"] == pytest.approx({ip["node"]: ip for ip in out["baseline"]["report"]["ips"]}["byrp"]["power_mw"])


def test_power_knob_l0_skip_and_sbwc_modes(env):
    _, l0 = _preview(env, {"target": "power_knob", "param": "pyramid_l0", "option": "skip"})
    assert l0["memory_power_mw"] < 0
    _, lossy = _preview(env, {"target": "compression", "buffer_id": "PYRAMID_L0", "option": "COMP_YUV_LOSSY"})
    _, off = _preview(env, {"target": "compression", "buffer_id": "PYRAMID_L0", "option": "COMP_OFF"})
    assert lossy["bw_mbs"] < 0 <= off["bw_mbs"]


def test_sbwc_baseline_uses_the_same_mean_ratio_as_the_lever(env):
    """Engine baseline and the compression lever price SBWC with typical_ratio: re-selecting is a no-op, OFF costs BW."""
    _, same = _preview(env, {"target": "compression", "buffer_id": "PYRAMID_L0", "option": "COMP_YUV_LOSSLESS"})
    assert all(v == pytest.approx(0, abs=1e-6) for v in same.values()), same
    _, off = _preview(env, {"target": "compression", "buffer_id": "PYRAMID_L0", "option": "COMP_OFF"})
    assert off["bw_mbs"] > 100 and off["memory_power_mw"] > 0
    _, off_l1 = _preview(env, {"target": "compression", "buffer_id": "PYRAMID_L1", "option": "COMP_OFF"})
    assert off_l1["bw_mbs"] > 0
    _, lossy = _preview(env, {"target": "compression", "buffer_id": "PYRAMID_L0", "option": "COMP_YUV_LOSSY"})
    assert -off["bw_mbs"] < lossy["bw_mbs"] < 0   # lossy saves only its increment over the current lossless SBWC


def test_sensor_swap_reshapes_chain_when_active_size_differs(env):
    _, _, t = env
    sensor = t["sensors"][0]
    other = next((o for o in sensor["options"] if o["size"] != sensor["size"]), None)
    if other is None:
        pytest.skip("fixture has no sensor mode with another active size")
    out, _ = _preview(env, {"target": "sensor_mode", "node_id": "sensor_rear", "option": other["id"]})
    assert any("센서 크기" in n for n in out["lever_notes"])


def test_schema_rejects_malformed_choice_changes():
    with pytest.raises(ValueError, match="option"):
        WhatIfChange(target="ip_mode", node_id="mtnr")
    with pytest.raises(ValueError, match="no value"):
        WhatIfChange(target="ip_mode", node_id="mtnr", option="LowPower", value=1)
    with pytest.raises(ValueError, match="buffer_id"):
        WhatIfChange(target="compression", option="COMP_OFF")
    WhatIfChange(target="compression", buffer_id="PYRAMID_L0", option="COMP_YUV_LOSSY", value=0.6)
    with pytest.raises(ValueError, match="option is only allowed"):
        WhatIfChange(target="fps", value=60, option="x")


def test_unsupported_compression_is_rejected(env):
    graph, scope, t = env
    row = next((b for b in t["buffers"] if any(o["supported"] is False for o in b["options"])), None)
    if row is None:
        pytest.skip("every declared buffer supports every catalog mode")
    mode = next(o["id"] for o in row["options"] if o["supported"] is False)
    with pytest.raises(Exception, match="does not list"):
        _preview(env, {"target": "compression", "buffer_id": row["id"], "option": mode})


def test_combine_each_reports_singles_all_and_best(env):
    _, scope, _ = env
    levers = [{"target": "history_interval", "value": 2}, {"target": "power_knob", "param": "pyramid_l0", "option": "skip"},
              {"target": "compression", "buffer_id": "TNR_PREV_L0", "option": "COMP_YUV_LOSSLESS"}]
    out = service.ask(MagicMock(), WhatIfAskRequest(**scope, ask="combine", changes=levers))
    combo = out["combine"]
    assert [r["key"] for r in combo["rows"]] == ["baseline", "0", "1", "2", "0+1+2"]
    assert combo["best"] is not None and out["answer"]["verdict"] == "ok"
    assert combo["interaction_mw"] is not None
    fact = WhatIfAskRequest(**scope, ask="combine", combine="factorial", changes=levers[:2])
    assert len(service.ask(MagicMock(), fact)["combine"]["rows"]) == 4
    with pytest.raises(ValueError):
        WhatIfAskRequest(**scope, ask="combine", changes=levers[:1])


def test_scaled_size_tracks_pyramid_rounding():
    assert scaled_size((255, 144), (4080, 2296), (3744, 2112)) == (234, 132)
    assert scaled_size((510, 287), (4080, 2296), (3744, 2112)) == (468, 264)
    assert scaled_size((1920, 1080), (4080, 2296), (3744, 2112)) is None


def test_reshape_preserves_unrelated_explicit_buffers():
    buffers = {key: {"size": "4080x2296"} for key in ("local", "other_camera", "history")}
    buffers["history"]["history"] = {"node_id": "mtnr"}
    buffers["pyramid"] = {"size": "2040x1148", "dma": {"node_id": "mtnr"}}
    variant = SimpleNamespace(node_configs={}, size_overrides={}, buffer_overrides={})
    graph = SimpleNamespace(variant=variant, scenario=SimpleNamespace(size_profile={}, pipeline={"buffers": buffers}),
                            pipeline_edges=[{"source": "mtnr", "target": "output", "buffer": "local"}])
    _reshape(graph, ["mtnr"], set(), (4080, 2296), (3744, 2112))
    assert variant.buffer_overrides == {"local": {"size": "3744x2112"}, "history": {"size": "3744x2112"},
                                        "pyramid": {"size": "1872x1056"}}


@pytest.mark.parametrize("reverse", [False, True])
def test_selected_sensor_rejects_final_fps_above_catalog_limit(env, reverse):
    choice = next(o for o in env[2]["sensors"][0]["options"] if o.get("fps") and o["fps"] < 240)
    changes = [{"target": "sensor_mode", "node_id": "sensor_rear", "option": choice["id"]},
               {"target": "fps", "value": choice["fps"] + 1}]
    with pytest.raises(Exception, match="selected sensor mode supports"):
        _preview(env, *(reversed(changes) if reverse else changes))


@pytest.mark.parametrize("n,mode", [(1, "each"), (6, "factorial"), (9, "each")])
def test_runtime_combine_limits_also_cover_inferred_plans(n, mode):
    # An LLM plan can select combine after request-schema validation has run.
    with pytest.raises(Exception, match="combine requires"):
        service._combine({}, {}, [{}] * n, mode)


def test_change_iq_is_per_option():
    from scenario_db.api.services.whatif_conditions import change_iq
    t = {"knobs": [{"param": "crop", "options": [{"id": "on", "iq_eval": "not_required"}, {"id": "off"}]}],
         "ip_modes": [{"id": "mtnr", "options": [{"id": "Low", "iq_eval": "required"}, {"id": "Eco", "iq_eval": "not_required"}]}]}
    assert change_iq({"target": "compression", "buffer_id": "B", "option": "COMP_YUV_LOSSY"}, t) == "trade"
    assert change_iq({"target": "compression", "buffer_id": "B", "option": "COMP_YUV_LOSSLESS"}, t) == "neutral"
    assert change_iq({"target": "power_knob", "param": "crop", "option": "on"}, t) == "neutral"
    assert change_iq({"target": "power_knob", "param": "crop", "option": "off"}, t) == "eval"
    assert change_iq({"target": "ip_mode", "node_id": "mtnr", "option": "Eco"}, t) == "neutral"
    assert change_iq({"target": "ip_mode", "node_id": "mtnr", "option": "Low"}, t) == "eval"
    assert change_iq({"target": "history_interval", "value": 2}, t) == "eval"
    assert change_iq({"target": "fps", "value": 24}, t) == "neutral"


def test_combine_recommends_iq_keeping_case_and_lists_the_trade(env, monkeypatch):
    from scenario_db.api.services import whatif_conditions
    _, scope, _ = env
    calls = []
    real = whatif_conditions.whatif_targets
    monkeypatch.setattr(service, "whatif_targets", lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setattr(whatif_conditions, "whatif_targets", lambda *a, **k: calls.append(1) or real(*a, **k))
    levers = [{"target": "history_interval", "value": 2},
              {"target": "compression", "buffer_id": "TNR_PREV_L0", "option": "COMP_YUV_LOSSLESS"}]
    out = service.ask(MagicMock(), WhatIfAskRequest(**scope, ask="combine", combine="factorial", changes=levers))
    combo = out["combine"]
    rows = {r["key"]: r for r in combo["rows"]}
    assert [lv["iq"] for lv in combo["levers"]] == ["eval", "neutral"]
    assert rows[combo["best_keep"]]["iq"] == "neutral" and combo["best_keep"] == "1"
    assert combo["best"] == combo["best_trade"] != combo["best_keep"] and rows[combo["best_trade"]]["iq"] == "eval"
    assert combo["trade_gain_mw"] < 0
    assert "화질 유지" in out["answer"]["headline"] and any("IQ trade 포함" in f for f in out["answer"]["facts"])
    assert len(calls) <= 2   # baseline targets + one shared lever-target set, not one per case


def test_compression_support_matches_exploration_rule(env):
    """What-if and exploration share compression_support: an undeclared endpoint makes the mode unknown (None)."""
    from scenario_db.sim.arch_exploration import compression_support
    graph, _, t = env
    for row in t["buffers"]:
        live = set(row["nodes"])
        for opt in row["options"]:
            if opt["id"] == "COMP_OFF":
                continue
            assert opt["supported"] == compression_support(graph, live, opt["id"])[0]
            if row["undeclared"] and opt["supported"] is not False:
                assert opt["supported"] is None and "not declared" in opt["support_reason"]
