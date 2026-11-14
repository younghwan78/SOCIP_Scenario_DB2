"""D-02 judgement contract: declared sinks / role stages / KPIs; undeclared scenarios keep the name rules."""

from __future__ import annotations

import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, assess, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.models.definition.usecase import JudgementContract, Pipeline  # noqa: E402
from scenario_db.sim.models import DVFSTable  # noqa: E402
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget, judgement_contract  # noqa: E402

YT = "uc-vid-youtube-e2600"


@pytest.fixture(scope="module")
def env():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    doc = read(FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml")
    tables = {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}
    raw = read(FIXTURE / "02_definition" / f"{YT}.yaml")
    return catalog, tables, raw


def with_contract(graph, contract):
    scenario = deepcopy(graph.scenario)
    pipeline = deepcopy(scenario.pipeline)
    if contract is None:
        pipeline.pop("judgement", None)
    else:
        pipeline["judgement"] = contract
    scenario.pipeline = pipeline
    return replace(graph, scenario=scenario)


def run(graph, tables):
    return analyze_timing_budget(graph, TimingBudgetOptions(), dvfs_tables=tables)


def test_model_validates_sinks_and_stages():
    with pytest.raises(ValueError, match="judgement sink 'nope'"):
        Pipeline.model_validate({"nodes": [{"id": "a", "ip_ref": "ip-x"}], "judgement": {"sinks": [{"node": "nope", "kind": "video"}]}})
    with pytest.raises(ValueError):
        JudgementContract.model_validate({"stages": {"decoder": "middle"}})
    assert JudgementContract().kpis == ["interval"]
    # undeclared pipelines serialise exactly as before (the ETL dumps with exclude_none)
    assert "judgement" not in Pipeline.model_validate({"nodes": [{"id": "a", "ip_ref": "ip-x"}]}).model_dump(exclude_none=True)


def test_declared_youtube_contract_matches_the_name_rules(env):
    catalog, tables, raw = env
    graph = graph_from_fixture(raw, "yt-1080p30-h264-sdr", catalog)
    assert judgement_contract(graph) is not None
    declared, named = run(graph, tables), run(with_contract(graph, None), tables)
    assert declared["verdict"] == named["verdict"]
    assert {k: declared["intervals"][k] for k in ("preview", "video", "streams")} == \
        {k: named["intervals"][k] for k in ("preview", "video", "streams")}
    assert [s["nodes"] for s in declared["stages"]] == [s["nodes"] for s in named["stages"]]


def test_sinks_choose_what_is_judged(env):
    catalog, tables, raw = env
    graph = graph_from_fixture(raw, "yt-1080p30-h264-sdr", catalog)
    only_decode = run(with_contract(graph, {"sinks": [{"node": "mfc_dec", "kind": "video"}]}), tables)
    assert only_decode["intervals"]["preview"]["ok"] is None and only_decode["intervals"]["video"]["node"] == "mfc_dec"
    # a declared sink that is inactive in the variant is not judged
    bg = graph_from_fixture(raw, "yt-1080p-audio-bg", catalog)
    r = run(bg, tables)
    assert r["intervals"]["preview"]["ok"] is None and r["intervals"]["video"]["ok"] is not None
    # nothing declared is active and no RT stage -> not_applicable instead of an unfounded ok
    gone = run(with_contract(bg, {"sinks": [{"node": "dpu", "kind": "preview"}]}), tables)
    assert gone["verdict"]["status"] == "not_applicable"


def test_role_stages_and_unmodeled_kpis(env):
    catalog, tables, raw = env
    graph = graph_from_fixture(raw, "yt-1080p30-h264-sdr", catalog)
    stages = lambda rep: {s["id"]: s["nodes"] for s in rep["stages"]}  # noqa: E731
    assert "mfc_dec" in stages(run(with_contract(graph, None), tables))["output"]
    r = run(with_contract(graph, {"stages": {"decoder": "nrt"}, "kpis": ["interval", "underrun", "frame_pacing"]}), tables)
    assert "mfc_dec" in stages(r)["nrt"] and "mfc_dec" not in stages(r)["output"]
    assert "판정 계약 KPI 미모델: underrun, frame_pacing" in r["verdict"]["notes"]


def test_evidence_assess_uses_the_declared_sinks(env):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    import generate_simulation_evidence as gen

    catalog, _, raw = env
    graph, inputs = gen.build_inputs(raw, "yt-1080p-audio-bg", catalog, 300)
    assert gen.declared_sinks(graph, inputs) == {"mfc_dec"}
    from scenario_db.sim.runner import run_simulation

    result = run_simulation(inputs, dvfs_tables={})
    assert assess(result, 30.0, 3.0, {"mfc_dec"})["accepted"]
    # the camera default finds no sink in screen-off playback
    assert not assess(result, 30.0, 3.0)["accepted"]


def test_condition_hash_follows_the_contract(env, monkeypatch):
    from types import SimpleNamespace

    from scenario_db.api.services import timing_budget as service
    from scenario_db.sim.models import SimulationRunConfig

    catalog, tables, raw = env
    monkeypatch.setattr(service, "_request_hash", lambda *a, **k: "inputs")
    shim = SimpleNamespace(config=SimulationRunConfig())
    graph = graph_from_fixture(raw, "yt-1080p30-h264-sdr", catalog)
    declared = service._condition_hash(graph, TimingBudgetOptions(), shim, tables)
    assert service._condition_hash(with_contract(graph, None), TimingBudgetOptions(), shim, tables) != declared
    other = with_contract(graph, {"sinks": [{"node": "mfc_dec", "kind": "video"}]})
    assert service._condition_hash(other, TimingBudgetOptions(), shim, tables) != declared


def test_no_active_declared_sink_is_never_accepted(env):
    import generate_simulation_evidence as gen
    from scenario_db.sim.runner import run_simulation

    catalog, _, raw = env
    raw2 = deepcopy(raw)
    docs = raw2 if isinstance(raw2, list) else [raw2]
    for d in docs:
        if d.get("pipeline", {}).get("judgement"):
            d["pipeline"]["judgement"]["sinks"] = [{"node": "dpu", "kind": "preview"}]
    graph, inputs = gen.build_inputs(raw2, "yt-1080p-audio-bg", catalog, 300)
    assert gen.declared_sinks(graph, inputs) == set()
    result = run_simulation(inputs, dvfs_tables={})
    assert not assess(result, 30.0, 3.0, set())["accepted"]


def test_interval_distribution_uses_the_declared_sinks(env):
    from scenario_db.sim.timing_budget import interval_distribution

    catalog, tables, raw = env
    graph = graph_from_fixture(raw, "yt-1080p30-h264-sdr", catalog)
    named = interval_distribution(with_contract(graph, None), TimingBudgetOptions(), dvfs_tables=tables, trials=2, frames=8)
    only = interval_distribution(with_contract(graph, {"sinks": [{"node": "mfc_dec", "kind": "video"}]}),
                                 TimingBudgetOptions(), dvfs_tables=tables, trials=2, frames=8)
    assert {s["node"] for s in named["streams"]} == {"dpu", "mfc_dec"}
    assert [(s["node"], s["kind"]) for s in only["streams"]] == [("mfc_dec", "video")]


def test_youtube_own_cadences_are_judged_and_their_cpu_work_counts(env):
    # D-04 (assumed fixture values): ABOX period IRQ 10 ms, network one chunk per 100 ms, ExoPlayer loop 10 ms
    catalog, tables, raw = env
    graph = graph_from_fixture(raw, "yt-1080p30-h264-sdr", catalog)
    report = run(graph, tables)
    rows = {r["node"]: r for r in report["own_cadence"]}
    assert set(rows) == {"abox", "exo_loop", "network"}
    assert rows["abox"] | {"releases": 0} == {"node": "abox", "cadence": "period", "period_ms": 10.0, "deadline_ms": 10.0,
                                               "releases": 0, "worst_response_ms": 0.6, "worst_slack_ms": 9.4, "ok": True}
    # SW on its own cadence runs on its own thread with its own runtime (statistic max: 9.0 / 0.5 ms)
    assert rows["network"]["cadence"] == "chunk" and rows["network"]["worst_response_ms"] == 9.0 and rows["network"]["ok"]
    assert rows["exo_loop"]["worst_response_ms"] == 0.5 and rows["exo_loop"]["releases"] >= 3
    # ... and is CPU work: runtime x frame period / own period
    period = report["period_ms"]
    cpu = report["power"]["cpu_by_task"]
    assert set(cpu) >= {"network", "exo_loop", "sw_demux"}
    assert cpu["network"] == pytest.approx(cpu["exo_loop"] * (9.0 * period / 100) / (0.5 * period / 10), rel=0.01)
    # outside the frame stages, as before
    assert not any(i["task"] in ("network", "exo_loop") for s in report["stages"] for i in s["sw_items"])


def test_an_undeclared_own_period_is_still_not_judged(env):
    catalog, tables, raw = env
    graph = graph_from_fixture(raw, "yt-1080p30-h264-sdr", catalog)
    report = run(graph, tables)
    plain = deepcopy(graph.variant)
    plain.node_configs = {**plain.node_configs, "abox": {**plain.node_configs["abox"],
                          "timeline": {k: v for k, v in plain.node_configs["abox"]["timeline"].items() if k != "cadence"}}}
    undeclared = run(replace(graph, variant=plain), tables)
    assert "abox" not in {r["node"] for r in undeclared["own_cadence"]}
    assert undeclared["verdict"] == report["verdict"] and undeclared["stages"] == report["stages"]


def test_voice_call_uplink_and_downlink_are_two_paths_not_a_cycle(env):
    # downlink modem -> audio_hal -> speaker, uplink mic -> audio_hal -> modem_tx (one modem node made a cycle)
    catalog, tables, _ = env
    raw = read(FIXTURE / "02_definition" / "uc-call-voice-e2600.yaml")
    edges = {(e["from"], e["to"]) for e in raw["pipeline"]["edges"]}
    assert edges == {("modem", "audio_hal"), ("audio_hal", "speaker"), ("mic", "audio_hal"), ("audio_hal", "modem_tx")}
    for v in raw["variants"]:
        report = run(graph_from_fixture(raw, v["id"], catalog), tables)
        # no RT output to judge: the verdict says so instead of failing to build the timeline
        assert report["verdict"]["status"] == "not_applicable"
        assert {"modem", "modem_tx"} <= set(report["power"]["cpu_by_task"])
        # the 20 ms voice frame on both paths is an own cadence judged by its own deadline (assumed fixture data)
        rows = {r["node"]: r for r in report["own_cadence"]}
        assert set(rows) == {"modem", "modem_tx"}
        assert all(r["cadence"] == "period" and r["period_ms"] == 20.0 and r["deadline_ms"] == 20.0 and r["ok"]
                   for r in rows.values())
        # its CPU work counts at the voice rate (50 / s), not at the default 30 fps frame rate
        period = report["period_ms"]
        assert report["power"]["cpu_by_task"]["modem"] > 0
        assert rows["modem"]["releases"] >= int(6 * period / 20)
