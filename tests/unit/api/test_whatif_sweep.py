from copy import deepcopy
from types import SimpleNamespace

import pytest

from scenario_db.api.schemas.scenario_whatif import WhatIfSweepRequest, WhatIfPreviewRequest
from scenario_db.api.services import whatif_sweep as sweep
from scenario_db.exceptions import ConflictError, UnprocessableError


def request(**updates):
    return WhatIfSweepRequest.model_validate({"project_ref": "p", "scenario_id": "s", "variant_id": "v",
        "expected_baseline_hash": "a" * 64, "axes": [{"label": "FPS", "values": [
            {"target": "fps", "value": 30}, {"target": "fps", "value": 60}]}], **updates})


def model(monkeypatch):
    base = {"analysis_hash": "b" * 64, "case": {"metrics": {"modeled_power_mw": 100}, "coverage": {}}}
    calls = []
    def preview(base, req):
        calls.append(req)
        fps = req.changes[0].value
        return {"candidate": {"metrics": {"modeled_power_mw": fps * 2, "bw_mbs": fps, "feasible": True},
            "coverage": {"missing_components": []}, "report": {"verdict": {"reasons": []},
                "latency": {"preview_ms": 100 / fps}}}, "delta": {"metrics": {}},
            "iq_required": [], "condition_hash": str(int(fps)) * 32}
    monkeypatch.setattr(sweep.engine, "_preview_from", preview)
    monkeypatch.setattr(sweep.engine, "_min_slack", lambda report: ("stage", 2., "stage"))
    monkeypatch.setattr(sweep.engine, "_baseline", lambda *args: base)
    return base, calls


def test_bounded_grid_fixed_policy_and_pareto(monkeypatch):
    base, calls = model(monkeypatch)
    original = deepcopy(base)
    result = sweep.run_sweep(None, request(comparison="fixed_opp"))
    assert result["total_cases"] == result["completed_cases"] == 2
    assert result["pareto_ids"] == ["case-1", "case-2"]  # lower power vs lower latency
    assert result["best_id"] == "case-1"
    assert all(c.comparison == "fixed_opp" for c in calls)
    assert WhatIfPreviewRequest.model_validate(result["rows"][0]["preview_request"]) == calls[0]
    assert base == original


def test_constraints_iq_and_missing_models_excluded(monkeypatch):
    model(monkeypatch)
    out = sweep.run_sweep(None, request(constraints={"max_power_mw": 70, "min_slack_ms": 1}))
    assert [r["eligible"] for r in out["rows"]] == [True, False]
    assert out["pareto_ids"] == ["case-1"]
    result = {"candidate": {"metrics": {"modeled_power_mw": 10, "bw_mbs": 1, "feasible": True},
        "coverage": {"missing_components": ["npu"]}, "report": {"latency": {}}}, "iq_required": ["crop"]}
    eligible, reasons, _, _ = sweep._eligibility(result, request(constraints={"max_latency_ms": 10}).constraints)
    assert not eligible and len(reasons) == 3


def test_resume_skips_completed_and_detects_drift(monkeypatch):
    _, calls = model(monkeypatch)
    first = sweep.run_sweep(None, request(), checkpoint=lambda out: out["completed_cases"] < 1)
    assert first["cancelled"] and first["completed_cases"] == 1
    second = sweep.run_sweep(None, request(), previous=first)
    assert second["completed_cases"] == 2 and not second["cancelled"]
    assert len(calls) == 2
    with pytest.raises(ConflictError):
        sweep.run_sweep(None, request(), previous={**first, "analysis_hash": "old"})


def test_domain_failure_is_one_row_and_limits_checked(monkeypatch):
    model(monkeypatch)
    monkeypatch.setattr(sweep.engine, "_preview_from", lambda *a: (_ for _ in ()).throw(UnprocessableError("incompatible mode")))
    out = sweep.run_sweep(None, request())
    assert out["best_id"] is None and all(r["reasons"] == ["incompatible mode"] for r in out["rows"])
    monkeypatch.setattr(sweep, "get_settings", lambda: SimpleNamespace(exploration_max_cases=1))
    with pytest.raises(UnprocessableError, match="case limit"):
        sweep.run_sweep(None, request())


def test_axis_validation_and_duplicate_targets():
    axis = request().axes[0].model_dump()
    with pytest.raises(ValueError, match="distinct"):
        request(axes=[axis, axis])
    with pytest.raises(ValueError, match="distinct"):
        request(axes=[{**axis, "values": [axis["values"][0]] * 2}])
    with pytest.raises(ValueError, match="one target"):
        request(axes=[{**axis, "values": [axis["values"][0], {"target": "node_param", "node_id": "n", "param": "ppc", "value": 2}]}])
