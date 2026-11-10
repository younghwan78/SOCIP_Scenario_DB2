"""An absent camera-frame judgement cannot establish timing feasibility."""

from pathlib import Path

import pytest

from scenario_db.sim import arch_exploration as ax
from scenario_db.sim import timing_budget as tb
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph, _read_yaml

ROOT = Path(__file__).resolve().parents[3]
AUDIO_VARIANTS = [
    (raw["id"], variant["id"])
    for raw in (
        _read_yaml(path)
        for path in sorted((ROOT / "db_Exynos2600_SM-S947B/02_definition").glob("uc-aud-*.yaml"))
    )
    for variant in raw["variants"]
]


@pytest.mark.parametrize("scenario,variant", AUDIO_VARIANTS)
def test_audio_has_no_timing_judgement(scenario, variant):
    report = tb.analyze_timing_budget(_exynos2600_generated_graph(scenario, variant))
    assert report["verdict"]["status"] == "not_applicable"
    assert report["verdict"]["reasons"] == []
    assert report["verdict"]["notes"] == [tb.NOT_APPLICABLE_NOTE]


@pytest.mark.parametrize("scenario,variant", [
    ("uc-game-play-e2600", "game-fhd-60fps-sdr"),
    ("uc-vid-playback-local-e2600", "vplay-local-h264-fhd30-sdr"),
    ("uc-vid-youtube-e2600", "yt-1080p30-h264-sdr"),
    ("uc-disp-gallery-e2600", "disp-gallery-fhd-sdr-60hz"),
    ("uc-cam-capture-e2600", "cam-cap-r1-sf"),
])
def test_judged_output_or_rt_keeps_the_existing_verdict(scenario, variant):
    report = tb.analyze_timing_budget(_exynos2600_generated_graph(scenario, variant))
    assert report["verdict"]["status"] in ("ok", "clock_up")
    assert tb.NOT_APPLICABLE_NOTE not in report["verdict"]["notes"]


def _verdict(rt_nodes=(), preview=None, video=None, streams=(), ips=()):
    stages = [{"id": "rt", "name": "RT", "nodes": list(rt_nodes), "feasible": True, "hw_ms": 0.0, "budget_ms": 25.0}]
    intervals = {"preview": {"ok": preview}, "video": {"ok": video}, "streams": list(streams), "target_ms": 33.333}
    return tb._verdict(stages, intervals, list(ips), period=33.333)


@pytest.mark.parametrize("kwargs", [
    {"rt_nodes": ["csis"]}, {"preview": True}, {"video": True}, {"streams": [{"ok": True}]},
])
def test_either_judgement_keeps_the_exact_ok_verdict(kwargs):
    assert _verdict(**kwargs) == {"status": "ok", "reasons": [], "notes": [], "nrt_clock_factor": None}


def test_real_failure_wins_over_no_judgement():
    ip = {"node": "audio", "stage": "nrt", "feasible": False, "infeasible_reason": "required clock exceeds maximum", "rule_clock_mhz": 0}
    verdict = _verdict(ips=[ip])
    assert verdict == {"status": "fail", "reasons": ["audio: required clock exceeds maximum"], "notes": [], "nrt_clock_factor": None}


def test_not_applicable_precedes_clock_up_only_when_nothing_was_judged():
    ip = {"node": "audio", "stage": "nrt", "feasible": True, "rule_clock_mhz": 100, "set_clock_mhz": 120}
    assert _verdict(ips=[ip])["status"] == "not_applicable"
    assert _verdict(rt_nodes=["csis"], ips=[ip]) == {"status": "clock_up", "reasons": [], "notes": [], "nrt_clock_factor": 1.2}


def test_audio_cannot_be_eligible_even_without_interval_or_power_constraints():
    graph = _exynos2600_generated_graph(*AUDIO_VARIANTS[0])
    spec = ax.ArchExplorationSpec.model_validate({"constraints": {"require_intervals": False, "require_power_model": False}})
    report = ax.explore_variant(graph, spec)
    assert report["baseline"]["verdict"] == "not_applicable"
    assert not report["spec_ok"] and report["counts"]["eligible"] == 0
    assert report["recommended"] is None
    assert report["levers"] == {"status": "none"}
    assert report["sw_margin"]["growth_tolerance"] is None
    assert report["sw_margin"]["recommendations"] == [tb.NOT_APPLICABLE_NOTE]
    fixed = ax._fixed_growth(report["slices"], spec.objective, {"dvfs": {}})
    assert fixed["growth_tolerance_fixed"] is None
    assert all(not row["ok"] for row in fixed["growth_fixed_rows"])
