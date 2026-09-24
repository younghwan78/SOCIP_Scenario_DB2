"""Timing-aware SW margin analysis (scenario_db.sim.sw_margin)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim import sw_margin as swm  # noqa: E402
from scenario_db.sim.models import IPTimingResult, SimulationRunConfig  # noqa: E402
from scenario_db.sim.runner import _with_calculated_durations  # noqa: E402

OVERHEAD = {
    "setup": {"min_ms": 0.5, "mean_ms": 1.0, "max_ms": 2.0},
    "completion": {"min_ms": 0.3, "mean_ms": 0.6, "max_ms": 1.5},
}
FAST = {"frames": 8}


@pytest.fixture(scope="module")
def graph_factory():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(
            id=d["id"],
            schema_version=d["schema_version"],
            category=d["category"],
            hierarchy=d["hierarchy"],
            capabilities=d["capabilities"],
            yaml_sha256="fixture",
        )
    raw = read(FIXTURE / "02_definition" / "uc-camera-recording.yaml")

    def build(variant: str):
        return graph_from_fixture(raw, variant, catalog)

    return build


def _ctx(graph, **options):
    options.setdefault("constraints", FAST)
    options.setdefault("grid_step", 0.05)
    opts = swm.SwMarginOptions(**options)
    return swm._context(graph, opts, SimulationRunConfig(), {}), opts


def test_serial_overhead_extends_task_occupancy():
    tasks = [
        {
            "id": "mtnr",
            "node_id": "mtnr",
            "hw_name": "MTNR",
            "task_type": "hw",
            "duration_ms": 0.0,
            "serial_overhead_ms": 2.5,
        }
    ]
    timing = [IPTimingResult(node_id="mtnr", hw_name="MTNR", hw_time_ms=10.0)]
    assert _with_calculated_durations(tasks, timing)[0]["duration_ms"] == pytest.approx(12.5)
    tasks[0].pop("serial_overhead_ms")
    assert _with_calculated_durations(tasks, timing)[0]["duration_ms"] == pytest.approx(10.0)


def test_required_margin_is_a_true_boundary(graph_factory):
    ctx, opts = _ctx(graph_factory("cam-rec-r1-fhd60-sdr"), statistic="max")
    solved = swm.solve_uniform_margin(ctx, opts.growth)
    assert solved["status"] == "solved"
    m = solved["margin"]
    assert swm.evaluate(ctx, m, opts.growth).feasible
    assert not swm.evaluate(ctx, max(0.0, m - 3 * opts.tolerance), opts.growth).feasible
    assert solved["binding"]


def test_cycle_constraint_matches_analytic_floor(graph_factory):
    # Relaxed latency: only C1 binds, so m* = 1 - (P - overhead) / ((1 + h_blank) P).
    graph = graph_factory("cam-rec-r1-uhd30-vdis")
    ctx, opts = _ctx(
        graph,
        statistic="mean",
        default_ip_overhead=OVERHEAD,
        constraints={**FAST, "latency_budget_frames": 20},
    )
    overhead = 1.0 + 0.6
    expected = 1 - (ctx.period_ms - overhead) / ((1 + ctx.h_blank) * ctx.period_ms)
    solved = swm.solve_uniform_margin(ctx, opts.growth)
    assert solved["margin"] == pytest.approx(expected, abs=3 * opts.tolerance)
    assert all(reason.startswith("C1") for reason in solved["binding"])


def test_sw_growth_never_lowers_required_margin(graph_factory):
    ctx, opts = _ctx(graph_factory("cam-rec-r1-fhd60-sdr"), statistic="max")
    margins = [
        swm.solve_uniform_margin(ctx, swm._scaled_growth(opts.growth, s))["margin"]
        for s in (1.0, 1.3, 1.6)
    ]
    assert None not in margins
    assert margins[0] <= margins[1] <= margins[2]
    assert margins[2] > margins[0]


def test_extra_sw_task_adds_its_runtime_to_the_chain(graph_factory):
    graph = graph_factory("cam-rec-r1-uhd30-vdis")
    ctx, opts = _ctx(graph, statistic="mean")
    base = swm.evaluate(ctx, 0.25, opts.growth)
    task = {
        "id": "new_ai_task",
        "after": "post_irta",
        "before": "mtnr",
        "runtime": {"min_ms": 3.0, "mean_ms": 3.0, "max_ms": 3.0},
    }
    # Dedicated core, first frame (no cross-frame contention): gated successor shifts by the runtime.
    growth = swm.SwGrowth(extra_tasks=[{**task, "resource_id": "CPU_NEW"}])
    ctx2, _ = _ctx(graph, statistic="mean", growth=growth)
    grown = swm.evaluate(ctx2, 0.25, growth)

    def first_frame_start(evaluation, node):
        return next(
            e.start_ms
            for e in evaluation.result.timeline_events
            if e.node_id == node and e.frame_index == 0
        )

    assert first_frame_start(grown, "mtnr") - first_frame_start(base, "mtnr") == pytest.approx(
        3.0, abs=1e-6
    )
    assert any(e.node_id == "new_ai_task" for e in grown.result.timeline_events)
    # Worst frame can grow by more than the runtime: shifted phases collide on shared CPU.
    assert grown.latency_ms["dpu"] - base.latency_ms["dpu"] >= 3.0 - 0.05
    shared = swm.SwGrowth(extra_tasks=[task])
    ctx3, _ = _ctx(graph, statistic="mean", growth=shared)
    contended = swm.evaluate(ctx3, 0.25, shared)
    assert contended.latency_ms["dpu"] - base.latency_ms["dpu"] >= 3.0 - 0.05


def test_growth_headroom_is_last_feasible_scale(graph_factory):
    ctx, opts = _ctx(graph_factory("cam-rec-r1-fhd60-sdr"), statistic="max")
    headroom = swm.solve_growth_headroom(ctx, 0.25, opts.growth)
    assert headroom["status"] == "solved"
    s = headroom["max_runtime_scale"]
    assert swm.evaluate(ctx, 0.25, swm._scaled_growth(opts.growth, s)).feasible
    assert not swm.evaluate(ctx, 0.25, swm._scaled_growth(opts.growth, s + 0.05)).feasible


def test_critical_breakdown_parts_sum_to_latency(graph_factory):
    ctx, opts = _ctx(
        graph_factory("cam-rec-r1-uhd30-vdis"), statistic="max", default_ip_overhead=OVERHEAD
    )
    evaluation = swm.evaluate(ctx, 0.25, opts.growth)
    crit = swm.critical_breakdown(ctx, evaluation)
    parts = crit["hw_ms"] + crit["sw_ms"] + crit["serial_overhead_ms"] + crit["wait_ms"]
    assert parts == pytest.approx(crit["latency_ms"], abs=0.01)
    assert crit["chain"][0].startswith("sensor") and crit["chain"][-1] == crit["sink"]
    assert crit["serial_overhead_ms"] > 0


def test_analysis_report_and_monte_carlo_are_reproducible(graph_factory):
    graph = graph_factory("cam-rec-r1-fhd60-sdr")
    options = swm.SwMarginOptions(
        statistic="max",
        monte_carlo_samples=3,
        seed=7,
        growth_sweep=[1.0, 1.2],
        per_ip_plan=True,
        constraints=FAST,
        grid_step=0.05,
    )
    first = swm.analyze_sw_margin(graph, options)
    second = swm.analyze_sw_margin(graph, options)
    assert first["monte_carlo"] == second["monte_carlo"]
    mc = first["monte_carlo"]
    assert 0.0 <= mc["rule_coverage"] <= 1.0
    # Sampled SW never exceeds the max statistic, so no sample needs more margin (+ one grid refinement).
    assert mc["max"] <= first["required"]["margin"] + 2 * options.tolerance
    assert first["rule"]["verdict"] in {
        "rule_adequate",
        "rule_over_provisioned",
        "rule_insufficient",
    }
    assert first["per_ip_plan"]["status"] == "solved"
    assert [row["runtime_scale"] for row in first["growth_sweep"]] == [1.0, 1.2]
    assert any("DVFS" in w for w in first["warnings"])


def test_analysis_does_not_mutate_graph(graph_factory):
    graph = graph_factory("cam-rec-r1-fhd60-sdr")
    before = (dict(graph.variant.design_conditions or {}), repr(graph.variant.node_configs))
    ctx, opts = _ctx(graph, statistic="min")
    swm.evaluate(ctx, 0.4, opts.growth)
    assert (dict(graph.variant.design_conditions or {}), repr(graph.variant.node_configs)) == before


def test_invalid_requests_are_rejected(graph_factory):
    graph = graph_factory("cam-rec-r1-uhd30-vdis")
    with pytest.raises(ValueError, match="unknown timeline task"):
        _ctx(graph, ip_overhead={"nope": OVERHEAD})
    with pytest.raises(ValueError, match="not a HW workload"):
        _ctx(graph, ip_overhead={"eis": OVERHEAD})
    with pytest.raises(ValueError, match="no timeline edge"):
        _ctx(
            graph,
            growth={
                "extra_tasks": [
                    {
                        "id": "x",
                        "after": "eis",
                        "before": "csis",
                        "runtime": {"min_ms": 1, "mean_ms": 1, "max_ms": 1},
                    }
                ]
            },
        )
    with pytest.raises(ValueError):
        swm.TimingStat(min_ms=2, mean_ms=1, max_ms=3)
    with pytest.raises(ValueError):
        swm.SwMarginOptions(rule_margin=0.95)


def test_verdict_classes():
    assert swm._verdict(0.25, None, 1e-3, 0.5) == "infeasible"
    assert swm._verdict(0.25, 0.6, 1e-3, 0.5) == "clock_unreachable"
    assert swm._verdict(0.25, 0.3, 1e-3, 0.5) == "rule_insufficient"
    assert swm._verdict(0.25, 0.1, 1e-3, 0.5) == "rule_over_provisioned"
    assert swm._verdict(0.25, 0.23, 1e-3, 0.5) == "rule_adequate"
