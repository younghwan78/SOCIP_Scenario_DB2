"""Frozen report projections retain an unsupported timing verdict."""

import pytest
from copy import deepcopy

from scenario_db.reporting import arch_report, review_sections, xlsx_export
from scenario_db.reporting.perf_sections import output_fps_block, output_rows
from scenario_db.reporting.review_verdict import scoreboard
from scenario_db.reporting.arch_conclusion import build_conclusion
from scenario_db.reporting.arch_opinions import build_opinions
from scenario_db.reporting.perf_sections import sw_requests
from scenario_db.reporting.review_verdict import data_quality, lever_actions, messages
from scenario_db.reporting.risk_rules import build_risks
from scenario_db.sim.arch_exploration import ArchExplorationSpec, explore_variant
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph


@pytest.fixture(scope="module")
def audio_snapshot():
    graph = _exynos2600_generated_graph("uc-aud-mp3-playback-e2600", "audio-mp3-screen-on")
    spec = ArchExplorationSpec()
    variant = explore_variant(graph, spec)
    run = {"id": "EXP-audio", "title": "audio", "scenario_type": "audio", "project_ref": graph.scenario.project_ref,
           "spec": spec.model_dump(mode="json"), "variants": [variant], "summary": {}}
    snap = arch_report.build_snapshot(run, {}, {})
    snap["review_context"] = {"policy": {"kpi": [{"variant_ref": graph.variant_id, "scenario_ref": graph.scenario_id}]}, "rows": []}
    return snap


def test_snapshot_and_html_tables_never_label_audio_as_satisfied(audio_snapshot):
    row = audio_snapshot["scenarios"][0]
    assert row["verdict"] == "not_applicable" and not row["spec_ok"]
    assert audio_snapshot["spec_summary"]["spec_fail"] == 0
    assert audio_snapshot["spec_summary"]["failed"] == []
    for html in (arch_report._scenarios([row]), arch_report._latency([row]), review_sections.dossier(audio_snapshot)):
        assert "class=meta>판정 미지원" in html
        assert ">fps 만족<" not in html and ">OK<" not in html


def test_output_and_scoreboard_distinguish_unjudged_audio_from_frame_drops(audio_snapshot):
    row = output_rows(audio_snapshot)[0]
    assert row["verdict"] == "not_applicable" and not row["spec_ok"] and not row["drop"]
    assert "<td class=meta>판정 미지원</td>" in output_fps_block(audio_snapshot)
    assert "출력 fps 충족 · 기타 spec 미달" not in output_fps_block(audio_snapshot)
    board = scoreboard(audio_snapshot)
    assert board and all(r["fps"]["state"] == "not_applicable" for r in board)
    assert all(r["fps"]["cls"] == "mute" and r["fps"]["label"] == "판정 미지원" for r in board)


def test_spreadsheet_uses_the_unsupported_label(audio_snapshot):
    sheets = {name: rows for name, _, rows in xlsx_export.report_sheets(audio_snapshot)}
    assert sheets["Scenario"][0][4] == "판정 미지원"
    assert sheets["Latency"][0][-1] == "판정 미지원"


def test_audio_conclusion_opinions_and_margin_lists_are_not_failures(audio_snapshot):
    conclusion = audio_snapshot["conclusion"]
    assert conclusion["headline"].count("판정 미지원 1건") == 1
    assert "조치 필요" not in conclusion["headline"]
    assert not any(action["tier"] == 0 for action in conclusion["actions"])
    assert audio_snapshot["sw_margin_fail"] == []
    assert audio_snapshot["sw_margin_top5"] == []
    for block in audio_snapshot["opinions"]:
        assert block["not_applicable"] == 1
        assert block["opinions"][0].count("판정 미지원 1건") == 1
        assert "미달" not in block["opinions"][0]
        assert not any("미달 원인" in text for text in block["opinions"])
        assert not any("모델 보정" in text for text, _ in block["sections"]["mitigation"])
        assert all(text.startswith("근거 보강:") or text == "추가 조치 불필요." for text, _ in block["sections"]["mitigation"])
    assert not any(row["key"] == "fail_without_power" for row in data_quality(audio_snapshot))
    assert messages(audio_snapshot, [], [])[0].count("판정 미지원 1건") == 1


def test_stored_negative_audio_margins_do_not_create_sw_actions(audio_snapshot):
    snap = deepcopy(audio_snapshot)
    row = snap["scenarios"][0]
    row["sw_margin_pct"] = -42.0
    row["sw_stages"] = [{"stage": "nrt", "basis": "stage", "bottleneck": "audio-worker", "sw_ms": 70.0,
                         "hw_ms": 0.0, "chain_ms": 70.0, "margin_pct": -42.0}]
    margin = {"scenario_id": row["scenario_id"], "variant_id": row["variant_id"], "verdict": "not_applicable",
              "margin_pct": -42.0, "stage": "nrt", "bottleneck": "audio-worker"}
    snap["sw_margin_top5"] = [margin]
    snap["sw_margin_fail"] = [margin]
    assert sw_requests(snap) == []
    assert not any(action["tier"] == 3 for action in lever_actions(snap))
    assert not any("SW timing margin" in risk["title"] for risk in build_conclusion(snap)["risks"])
    assert not any("sw_margin" in risk["key"] for risk in build_risks(snap))
    assert "SW margin</th>" not in review_sections.dossier(snap)
    assert "-42.0" not in arch_report._margins([margin])
    assert output_rows(snap)[0]["margin_pct"] is None


def test_mixed_audio_and_real_failure_counts_only_the_real_failure(audio_snapshot):
    snap = deepcopy(audio_snapshot)
    failed = deepcopy(snap["scenarios"][0])
    failed.update(variant_id="judged-failure", verdict="fail", reasons=["RT budget exceeded"])
    snap["scenarios"].append(failed)
    snap["spec_summary"].update(explored=2, spec_fail=1, failed=[{
        "scenario_id": failed["scenario_id"], "variant_id": failed["variant_id"], "reasons": failed["reasons"],
    }])
    conclusion = build_conclusion(snap)
    assert "미달 1개는 조치 필요" in conclusion["headline"]
    assert conclusion["headline"].count("판정 미지원 1건") == 1
    assert all("audio-mp3-screen-on" not in action["targets"] for action in conclusion["actions"])
    block = build_opinions(snap["scenarios"], [])[0]
    assert "미달 1개" in block["opinions"][0]
    assert block["opinions"][0].count("판정 미지원 1건") == 1
    assert messages(snap, [], [])[0].count("판정 미지원 1건") == 1
