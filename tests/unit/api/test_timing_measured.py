"""S4: a measurement as Timing Budget input (SW runtime / IP clock / CPU profile) — request transformation."""

from types import SimpleNamespace

import pytest

from scenario_db.api.schemas.timing_budget import MeasuredInputs, TimingBudgetRequest
from scenario_db.api.services import timing_budget as svc
from scenario_db.exceptions import UnprocessableError


def _row(**kw):
    base = {"id": "meas-1", "scenario_ref": "uc-a", "variant_ref": "v1", "kind": "evidence.measurement",
            "sw_task_timing": [], "metric_observations": []}
    return SimpleNamespace(**(base | kw))


def test_sw_stats_fill_missing_min_max_and_scale_invocations():
    row = _row(sw_task_timing=[
        {"task": "post_irta", "mean_ms": 5.0, "p50_ms": 4.5, "p95_ms": 7.0},
        {"task": "storage_write", "mean_ms": 2.0, "min_ms": 1.0, "max_ms": 3.0, "sample_unit": "invocation", "count_per_frame": 2},
        {"task": "no_mean", "max_ms": 3.0},
        {"task": "inactive", "mean_ms": 3.0, "count_per_frame": 0},
    ])
    st = svc._sw_stats(row)
    assert st["post_irta"] == {"min_ms": 4.5, "mean_ms": 5.0, "max_ms": 7.0}
    assert st["storage_write"] == {"min_ms": 2.0, "mean_ms": 4.0, "max_ms": 6.0}
    assert "no_mean" not in st
    assert st["inactive"] == {"min_ms": 0, "mean_ms": 0, "max_ms": 0}


def test_apply_measured_turns_flags_into_explicit_options_and_config(monkeypatch):
    row = _row(sw_task_timing=[{"task": "post_irta", "mean_ms": 5.0, "min_ms": 4.0, "max_ms": 7.0}])
    monkeypatch.setattr(svc, "_measurement", lambda db, request: row)
    monkeypatch.setattr(svc, "_clock_count", lambda r: 3)
    req = TimingBudgetRequest(scenario_id="uc-a", variant_id="v1",
                              measured=MeasuredInputs(measurement_ref="meas-1", sw=True, clock=True, cpu=True))
    out = svc.apply_measured(None, req)
    assert out.options.task_runtime["post_irta"].mean_ms == 5.0
    assert out.options.cpu_model == "profile" and out.options.cpu_profile_ref == "meas-1"
    assert out.config.measured_clock_ref == "meas-1" and out.config.clock_basis == "measured"
    # throughput stays unset so the project review policy still decides it
    assert "throughput_model" not in out.options.model_fields_set
    # compare-only (no flags) leaves the request as is
    plain = TimingBudgetRequest(scenario_id="uc-a", variant_id="v1", measured=MeasuredInputs(measurement_ref="meas-1"))
    assert svc.apply_measured(None, plain) is plain


def test_apply_measured_refuses_missing_parts(monkeypatch):
    monkeypatch.setattr(svc, "_measurement", lambda db, request: _row())
    monkeypatch.setattr(svc, "_clock_count", lambda r: 0)
    for flag in ("sw", "clock"):
        req = TimingBudgetRequest(scenario_id="uc-a", variant_id="v1", measured=MeasuredInputs(measurement_ref="meas-1", **{flag: True}))
        with pytest.raises(UnprocessableError):
            svc.apply_measured(None, req)


def test_explicit_measured_cpu_cannot_fall_back_to_flat():
    req = TimingBudgetRequest(scenario_id="uc-a", variant_id="v1",
                              measured=MeasuredInputs(measurement_ref="meas-1", cpu=True))
    with pytest.raises(UnprocessableError, match="cpu.clusters"):
        svc._validate_measured_cpu(req, req.options, req.config)
    legacy = TimingBudgetRequest(scenario_id="uc-a", variant_id="v1", options={"cpu_model": "profile"})
    svc._validate_measured_cpu(legacy, legacy.options, legacy.config)
