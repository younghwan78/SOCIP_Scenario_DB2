"""What-if ask: builder conditions / in-house LLM interpretation -> executed answer (DVFS level, limit search, bottleneck)."""
import json
from types import SimpleNamespace

import httpx
import pytest
import yaml
from pydantic import SecretStr, ValidationError

from scenario_db.api.schemas.scenario_whatif import WhatIfAskRequest, WhatIfChange
from scenario_db.api.services import scenario_whatif as service
from scenario_db.api.services import whatif_llm
from scenario_db.api.services.whatif_conditions import apply_whatif_changes
from scenario_db.sim.models import DVFSTable, SimulationRunConfig
from tests.unit.api.test_scenario_whatif import _graph
from tests.unit.sim.test_timing_budget import DVFS_PATH

FASTER = {"dvfs_overrides": {"INTCAM": 2, "CAM": 4}}   # baseline above the lowest OPP so levels can go down


@pytest.fixture(scope="module")
def tables():
    doc = yaml.safe_load(DVFS_PATH.read_text(encoding="utf-8"))
    return {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}


@pytest.fixture
def scope(monkeypatch, tables):
    graph = _graph()
    monkeypatch.setattr(service, "_load", lambda *a: (graph, tables, "dvfs-sample"))
    monkeypatch.setattr(service, "_apply_config_profile", lambda *a: None)
    monkeypatch.setattr(service, "scenario_policy", lambda *a: None)
    return dict(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id, variant_id=graph.variant_id)


def _llm(monkeypatch, reply):
    monkeypatch.setattr(whatif_llm, "_chat", lambda messages: (json.dumps(reply) if isinstance(reply, dict) else reply, 7))


def test_targets_list_dvfs_domains_with_ladder_and_offer_the_level_condition(scope):
    t = service.targets(None, service.WhatIfScope(**scope))
    intcam = next(d for d in t["domains"] if d["id"] == "INTCAM")
    assert intcam["level"] == 5 and intcam["index"] == 0            # sample table: already the lowest OPP
    assert [lv["level"] for lv in intcam["ladder"]][:2] == [5, 4]    # slow -> fast
    assert set(intcam["ips"]) == {"msnr", "mtnr"}
    assert "dvfs_level" in t["supported_changes"]
    assert next(n for n in t["nodes"] if n["id"] == "mtnr")["clock_mhz"] == 133.0
    assert [a["ask"] for a in t["asks"]] == ["what_if", "search_limit", "diagnose"]
    assert t["llm"]["available"] is False


def test_builder_level_change_answers_feasibility_power_and_clocks(scope):
    out = service.ask(None, WhatIfAskRequest(**scope, config=FASTER, changes=[{"target": "dvfs_level", "domain": "INTCAM", "level": 3}]))
    up = service.ask(None, WhatIfAskRequest(**scope, changes=[{"target": "dvfs_level", "domain": "INTCAM", "level": 4}]))
    assert up["answer"]["actions"] == []        # baseline already at the lowest OPP: no limit search to offer
    a = out["answer"]
    assert out["interpretation"] is None and a["verdict"] == "ok"
    assert a["headline"].startswith("INTCAM L2→L3 (400 MHz): timing 충족")
    assert out["result"]["delta"]["metrics"]["modeled_power_mw"] < 0
    assert any("mtnr 533→400 MHz" in f for f in a["facts"])
    assert a["actions"] == [{"label": "INTCAM 어디까지 낮출 수 있나", "ask": "search_limit", "search_domains": ["INTCAM"]}]


def test_search_limit_walks_the_ladder_to_the_lowest_feasible_level(scope):
    out = service.ask(None, WhatIfAskRequest(**scope, config=FASTER, ask="search_limit", search_domains=["INTCAM"]))
    row = out["search"][0]
    assert row["domain"] == "INTCAM" and row["level"] == 2
    assert [r["level"] for r in row["rows"]] == [3, 4, 5] and all(r["feasible"] for r in row["rows"])
    assert row["lowest"]["level"] == 5 and row["lowest"]["delta_mw"] < 0
    assert "L5 (133 MHz)까지 3단계 가능" in out["answer"]["headline"]


def test_diagnose_names_the_tightest_stage_and_domain_room(scope):
    out = service.ask(None, WhatIfAskRequest(**scope, ask="diagnose"))
    d = out["diagnose"]
    assert d["tight"]["slack_ms"] == min(s["slack_ms"] for s in d["stages"])
    assert {x["id"]: x["down"] for x in d["domains"]} == {"CAM": 0, "INT": 0, "INTCAM": 0}
    assert out["answer"]["verdict"] == "ok" and out["answer"]["headline"].startswith("가장 빠듯한 구간 ")
    assert out["answer"]["actions"] == []                           # nothing can go lower


def test_question_without_llm_returns_the_reason_and_no_answer(scope):
    out = service.ask(None, WhatIfAskRequest(**scope, query="INTCAM level 하나 낮추면 timing 괜찮아?"))
    assert out["interpretation"]["status"] == "llm_unavailable"
    assert "설정되지 않았습니다" in out["interpretation"]["reason"]
    assert out["answer"] is None and out["result"] is None


def test_llm_level_step_past_the_lowest_opp_is_answered_as_a_boundary(scope, monkeypatch):
    _llm(monkeypatch, {"ask": "what_if", "changes": [{"target": "dvfs_level", "domain": "INTCAM", "shift": -1}], "focus": ["timing"]})
    out = service.ask(None, WhatIfAskRequest(**scope, query="INTCAM level을 하나 낮추면 timing에 문제가 없어?"))
    assert out["interpretation"]["status"] == "boundary" and out["interpretation"]["used"] == "llm"
    assert out["answer"]["verdict"] == "boundary"
    assert out["answer"]["headline"] == "INTCAM는 이미 최저 OPP L5 (133 MHz)라 더 낮출 level이 없습니다"
    assert out["answer"]["facts"][0].startswith("현재 timing 충족 · 가장 빠듯한 구간")


def test_llm_relative_step_resolves_against_the_baseline_ladder(scope, monkeypatch):
    _llm(monkeypatch, {"ask": "what_if", "changes": [{"target": "dvfs_level", "domain": "INTCAM", "shift": -1}]})
    out = service.ask(None, WhatIfAskRequest(**scope, config=FASTER, query="INTCAM 한 단계 낮추면?"))
    assert out["plan"]["changes"] == [{"target": "dvfs_level", "domain": "INTCAM", "level": 3}]
    assert out["answer"]["verdict"] == "ok"


def test_llm_output_is_validated_against_this_variant(scope, monkeypatch):
    _llm(monkeypatch, {"ask": "what_if", "changes": [{"target": "dvfs_level", "domain": "NOPE", "shift": -1},
                                                     {"target": "node_clock_mhz", "node_id": "mfc_enc", "scale": 0.8},
                                                     {"target": "node_clock_mhz", "node_id": "ghost", "value": 300}],
                       "unsupported": [{"text": "EIS 끄면", "reason": "기능 on/off는 다른 variant"}]})
    out = service.ask(None, WhatIfAskRequest(**scope, query="q"))
    assert out["plan"]["changes"] == [{"target": "node_clock_mhz", "node_id": "mfc_enc", "value": 106.4}]   # 133 × 0.8
    reasons = [i["reason"] for i in out["interpretation"]["ignored"]]
    assert reasons[0] == "기능 on/off는 다른 variant"
    assert any("없는 DVFS domain: NOPE" in r for r in reasons) and any("없는 대상: ghost" in r for r in reasons)
    # a lower bound below the applied clock changes nothing — the answer says so and points to DVFS level
    assert any("하한이라 적용 clock은 그대로 (낮추려면 DVFS level 조건: INT)" in f for f in out["answer"]["facts"])


def test_llm_clarification_waits_for_a_choice(scope, monkeypatch):
    _llm(monkeypatch, {"ask": "what_if", "changes": [], "clarification": {"message": "얼마나?", "choices": [
        {"label": "−1", "change": {"target": "dvfs_level", "domain": "CAM", "shift": -1}},
        {"label": "L3", "change": {"target": "dvfs_level", "domain": "CAM", "level": 3}}]}})
    out = service.ask(None, WhatIfAskRequest(**scope, query="CAM 낮추면?"))
    assert out["interpretation"]["status"] == "clarification" and out["answer"] is None
    # −1 from the lowest OPP is not a valid choice; L3 is kept as a complete change
    assert out["interpretation"]["clarification"]["choices"] == [{"label": "L3", "change": {"target": "dvfs_level", "domain": "CAM", "level": 3}}]


def test_unusable_llm_reply_is_reported_not_guessed(scope, monkeypatch):
    _llm(monkeypatch, "sorry, I cannot")
    out = service.ask(None, WhatIfAskRequest(**scope, query="q"))
    assert out["interpretation"] == {"status": "llm_unavailable", "reason": "사내 LLM 응답이 JSON이 아닙니다", "available": False, "model": None}


def _configured(monkeypatch):
    s = SimpleNamespace(whatif_llm_base_url="http://llm.internal/v1/", whatif_llm_model="in-house", whatif_llm_api_key=SecretStr("k"),
                        whatif_llm_timeout_s=3.0, whatif_llm_json_mode=True)
    monkeypatch.setattr(whatif_llm, "get_settings", lambda: s)


def test_chat_completions_call_retries_without_json_mode_and_reports_timeouts(monkeypatch):
    _configured(monkeypatch)
    calls = []

    def post(self, url, json=None, headers=None):
        calls.append((url, dict(json), headers["Authorization"]))
        if len(calls) == 1:
            return httpx.Response(400, request=httpx.Request("POST", url))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ask":"diagnose"}'}}]}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", post)
    content, _ = whatif_llm._chat([{"role": "user", "content": "x"}])
    assert content == '{"ask":"diagnose"}'
    assert calls[0][0] == "http://llm.internal/v1/chat/completions" and calls[0][2] == "Bearer k"
    assert "response_format" in calls[0][1] and "response_format" not in calls[1][1]
    assert calls[1][1]["temperature"] == 0

    def slow(self, url, json=None, headers=None):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(httpx.Client, "post", slow)
    with pytest.raises(whatif_llm.LlmUnavailable, match="응답 시간 초과"):
        whatif_llm._chat([{"role": "user", "content": "x"}])


def test_dvfs_level_change_schema_and_apply_bounds(tables):
    with pytest.raises(ValidationError, match="require level"):
        WhatIfChange(target="dvfs_level", domain="CAM", value=3)
    with pytest.raises(ValidationError, match="level is only allowed"):
        WhatIfChange(target="fps", value=30, level=2)
    with pytest.raises(ValidationError, match="dvfs_level requires domain"):
        WhatIfChange(target="dvfs_level", level=2)
    graph = _graph()
    domains = [{"id": "CAM", "ladder": [{"level": 7, "mhz": 133.0}, {"level": 6, "mhz": 200.0}]}]
    _, cfg, _ = apply_whatif_changes(graph, [WhatIfChange(target="dvfs_level", domain="CAM", level=6)], SimulationRunConfig(), domains)
    assert cfg.dvfs_overrides == {"CAM": 6}
    with pytest.raises(ValueError, match="no OPP level L2"):
        apply_whatif_changes(graph, [WhatIfChange(target="dvfs_level", domain="CAM", level=2)], SimulationRunConfig(), domains)
    with pytest.raises(ValueError, match="unsupported DVFS domain"):
        apply_whatif_changes(graph, [WhatIfChange(target="dvfs_level", domain="MIF", level=2)], SimulationRunConfig(), domains)
