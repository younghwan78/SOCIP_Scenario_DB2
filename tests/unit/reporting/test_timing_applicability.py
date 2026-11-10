"""Frozen report projections retain an unsupported timing verdict."""

import pytest

from scenario_db.reporting import arch_report, review_sections, xlsx_export
from scenario_db.reporting.perf_sections import output_fps_block, output_rows
from scenario_db.reporting.review_verdict import scoreboard
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
