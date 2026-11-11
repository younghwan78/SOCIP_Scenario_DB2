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
