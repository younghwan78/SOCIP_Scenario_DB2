from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scenario_db.models.common import ViolationAction
from scenario_db.models.evidence.common import ExecutionContext, SweepContext
from scenario_db.models.evidence.measurement import (
    MeasuredKpi,
    MeasurementEvidence,
    Provenance,
    RuntimeSwState,
)
from scenario_db.models.evidence.resolution import (
    FeatureCheck,
    HwNodeResolution,
    HwViolation,
    OverallFeasibility,
    ResolutionResult,
    SwResolution,
    SwViolation,
    ViolationSummary,
)
from scenario_db.models.evidence.simulation import (
    IpBreakdown,
    SimulationEvidence,
    SubmoduleBreakdown,
)

FIXTURES = Path(__file__).parent / "fixtures" / "evidence"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def roundtrip(model_cls, path: Path, **dump_kwargs):
    raw = load_yaml(path)
    obj = model_cls.model_validate(raw)
    serialised = obj.model_dump(exclude_none=True, **dump_kwargs)
    obj2 = model_cls.model_validate(serialised)
    assert obj == obj2
    return obj


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

def test_sim_evidence_roundtrip():
    obj = roundtrip(SimulationEvidence, FIXTURES / "sim-camera-recording-UHD60-A0-sw123.yaml")
    assert obj.kind == "evidence.simulation"
    assert obj.scenario_ref == "uc-camera-recording"
    assert obj.variant_ref == "UHD60-HDR10-H265"
    assert obj.execution_context.sw_baseline_ref == "sw-vendor-v1.2.3"


def test_meas_evidence_roundtrip():
    obj = roundtrip(MeasurementEvidence, FIXTURES / "meas-camera-recording-UHD60-A0-sw123.yaml")
    assert obj.kind == "evidence.measurement"
    assert obj.aggregation.strategy == "mean_with_ci_95"


# ---------------------------------------------------------------------------
# ExecutionContext
# ---------------------------------------------------------------------------

def test_execution_context_sw_ref_is_document_id():
    """sw_baseline_ref must be a valid DocumentId (FK to sw_profiles)."""
    ctx = ExecutionContext.model_validate({
        "silicon_rev": "A0",
        "sw_baseline_ref": "sw-vendor-v1.2.3",
        "thermal": "hot",
    })
    assert ctx.sw_baseline_ref == "sw-vendor-v1.2.3"


def test_execution_context_invalid_sw_ref():
    with pytest.raises(ValidationError):
        ExecutionContext.model_validate({
            "silicon_rev": "A0",
            "sw_baseline_ref": "vendor-v1.2.3",  # missing prefix
            "thermal": "hot",
        })


# ---------------------------------------------------------------------------
# SweepContext
# ---------------------------------------------------------------------------

def test_sweep_context_parsed():
    ctx = SweepContext.model_validate({
        "sweep_job_id": "sweep-job-20260419-abc123",
        "sweep_definition_ref": "zoom_sweep",
        "sweep_axis": "size_profile.transforms[1].crop_ratio",
        "sweep_value": 0.5,
        "sweep_index": 1,
        "sweep_total_runs": 4,
    })
    assert ctx.sweep_job_id == "sweep-job-20260419-abc123"
    assert ctx.sweep_value == 0.5
    assert ctx.sweep_index == 1


# ---------------------------------------------------------------------------
# OverallFeasibility enum
# ---------------------------------------------------------------------------

def test_overall_feasibility_enum():
    assert set(OverallFeasibility) == {
        "production_ready", "exploration_only", "infeasible", "research_mode"
    }


# ---------------------------------------------------------------------------
# FeatureCheck status
# ---------------------------------------------------------------------------

def test_feature_check_status_pass():
    fc = FeatureCheck.model_validate({
        "feature": "LLC_dynamic_allocation",
        "required": "enabled",
        "actual": "enabled",
        "status": "PASS",
    })
    assert fc.status == "PASS"


def test_feature_check_status_fail():
    fc = FeatureCheck.model_validate({
        "feature": "LLC_per_ip_partition",
        "required": "enabled",
        "actual": "disabled",
        "status": "FAIL",
    })
    assert fc.status == "FAIL"


def test_feature_check_invalid_status():
    with pytest.raises(ValidationError):
        FeatureCheck.model_validate({
            "feature": "x", "required": "y", "actual": "z", "status": "UNKNOWN"
        })


# ---------------------------------------------------------------------------
# Violation structures — HW and SW are separate contexts (review #1)
# ---------------------------------------------------------------------------

def test_hw_violation_structure():
    v = HwViolation.model_validate({
        "requirement": "throughput_mpps",
        "requested": 1000,
        "provided": 800,
        "action_taken": "WARN_AND_CAP",
        "gap_pct": 25.0,
        "reason": "exceeds HW capability_max",
    })
    assert v.action_taken == ViolationAction.WARN_AND_CAP
    assert v.gap_pct == 25.0


def test_sw_violation_structure():
    v = SwViolation.model_validate({
        "feature": "LLC_per_ip_partition",
        "required": "enabled",
        "actual": "disabled",
        "action_taken": "WARN_AND_EMULATE",
        "emulation_note": "simulated via software partition",
    })
    assert v.action_taken == ViolationAction.WARN_AND_EMULATE
    assert v.emulation_note == "simulated via software partition"


def test_hw_sw_violations_in_separate_contexts():
    """HwViolation lives in HwNodeResolution, SwViolation in SwResolution — no union needed."""
    hw = HwNodeResolution.model_validate({
        "matched_mode": "high_throughput",
        "violations": [{"requirement": "throughput_mpps", "action_taken": "WARN_AND_CAP"}],
    })
    assert isinstance(hw.violations[0], HwViolation)

    sw = SwResolution.model_validate({
        "profile_ref": "sw-vendor-v1.2.3",
        "violations": [{
            "feature": "LLC_per_ip_partition",
            "required": "enabled",
            "actual": "disabled",
            "action_taken": "WARN_AND_EMULATE",
        }],
    })
    assert isinstance(sw.violations[0], SwViolation)


# ---------------------------------------------------------------------------
# IpBreakdown with InstanceId
# ---------------------------------------------------------------------------

def test_ip_breakdown_with_submodules():
    bd = IpBreakdown.model_validate({
        "ip": "ip-isp-v12",
        "power_mW": 780.0,
        "submodules": [
            {"sub": "ISP.TNR", "power_mW": 320.0},
            {"sub": "ISP.3AA0", "power_mW": 210.0},
        ],
    })
    assert bd.submodules[0].sub == "ISP.TNR"
    assert bd.submodules[1].sub == "ISP.3AA0"


def test_ip_breakdown_submodule_invalid_instance_id():
    with pytest.raises(ValidationError):
        IpBreakdown.model_validate({
            "ip": "ip-isp-v12",
            "power_mW": 780.0,
            "submodules": [{"sub": "isp.tnr", "power_mW": 100.0}],  # lowercase → invalid InstanceId
        })


# ---------------------------------------------------------------------------
# MeasuredKpi union parsing (review #4)
# ---------------------------------------------------------------------------

def test_measured_kpi_flat_number_stays_float():
    """A plain number in meas KPI must remain float/int, not coerced to MeasuredKpi."""
    obj = MeasurementEvidence.model_validate({
        "id": "meas-test-01",
        "schema_version": "2.2",
        "kind": "evidence.measurement",
        "scenario_ref": "uc-camera-recording",
        "variant_ref": "UHD60-HDR10-H265",
        "execution_context": {
            "silicon_rev": "A0",
            "sw_baseline_ref": "sw-vendor-v1.2.3",
            "thermal": "hot",
        },
        "provenance": {"device_id": "DEV-001"},
        "aggregation": {"strategy": "single_run"},
        "kpi": {"frame_latency_ms": 15.3},
    })
    assert obj.kpi["frame_latency_ms"] == 15.3
    assert isinstance(obj.kpi["frame_latency_ms"], float)


def test_measured_kpi_stat_object_parsed_as_model():
    """A dict with mean/n keys must be parsed as MeasuredKpi instance."""
    obj = MeasurementEvidence.model_validate({
        "id": "meas-test-02",
        "schema_version": "2.2",
        "kind": "evidence.measurement",
        "scenario_ref": "uc-camera-recording",
        "variant_ref": "UHD60-HDR10-H265",
        "execution_context": {
            "silicon_rev": "A0",
            "sw_baseline_ref": "sw-vendor-v1.2.3",
            "thermal": "hot",
        },
        "provenance": {},
        "aggregation": {"strategy": "mean_with_ci_95"},
        "kpi": {
            "total_power_mw": {"mean": 2150.0, "p95": 2240.0, "std": 45.0, "n": 10}
        },
    })
    kpi_val = obj.kpi["total_power_mw"]
    assert isinstance(kpi_val, MeasuredKpi)
    assert kpi_val.mean == 2150.0
    assert kpi_val.n == 10


def test_measured_kpi_mixed_flat_and_stat():
    """Same dict can have both flat float and MeasuredKpi values."""
    obj = MeasurementEvidence.model_validate({
        "id": "meas-test-03",
        "schema_version": "2.2",
        "kind": "evidence.measurement",
        "scenario_ref": "uc-camera-recording",
        "variant_ref": "UHD60-HDR10-H265",
        "execution_context": {
            "silicon_rev": "A0",
            "sw_baseline_ref": "sw-vendor-v1.2.3",
            "thermal": "hot",
        },
        "provenance": {},
        "aggregation": {"strategy": "mean_with_ci_95"},
        "kpi": {
            "total_power_mw": {"mean": 2150.0, "n": 10},
            "frame_latency_ms": 15.3,
        },
    })
    assert isinstance(obj.kpi["total_power_mw"], MeasuredKpi)
    assert isinstance(obj.kpi["frame_latency_ms"], float)


# ---------------------------------------------------------------------------
# KPI key format validation (review #3)
# ---------------------------------------------------------------------------

def test_sim_kpi_key_invalid_camelcase():
    """CamelCase KPI key must raise ValidationError."""
    with pytest.raises(ValidationError, match="lowercase snake_case"):
        SimulationEvidence.model_validate({
            "id": "sim-test-01",
            "schema_version": "2.2",
            "kind": "evidence.simulation",
            "scenario_ref": "uc-camera-recording",
            "variant_ref": "UHD60-HDR10-H265",
            "execution_context": {
                "silicon_rev": "A0",
                "sw_baseline_ref": "sw-vendor-v1.2.3",
                "thermal": "hot",
            },
            "run": {"timestamp": "2026-04-19T10:00:00+09:00", "tool": "sim", "source": "calculated"},
            "aggregation": {"strategy": "single_run"},
            "kpi": {"TotalPowerMw": 2150},   # CamelCase — invalid
        })


def test_meas_kpi_key_invalid_with_space():
    with pytest.raises(ValidationError, match="lowercase snake_case"):
        MeasurementEvidence.model_validate({
            "id": "meas-test-04",
            "schema_version": "2.2",
            "kind": "evidence.measurement",
            "scenario_ref": "uc-camera-recording",
            "variant_ref": "UHD60-HDR10-H265",
            "execution_context": {
                "silicon_rev": "A0",
                "sw_baseline_ref": "sw-vendor-v1.2.3",
                "thermal": "hot",
            },
            "provenance": {},
            "aggregation": {"strategy": "mean_with_ci_95"},
            "kpi": {"total power mw": 2150},  # space — invalid
        })


# ---------------------------------------------------------------------------
# ViolationAction from common.py (review #2)
# ---------------------------------------------------------------------------

def test_violation_action_imported_from_common():
    """ViolationAction must be importable from common, not only from usecase."""
    from scenario_db.models.common import ViolationAction as VA
    assert VA.FAIL_FAST == "FAIL_FAST"
    assert VA.WARN_AND_CAP == "WARN_AND_CAP"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def test_provenance_runtime_sw_state():
    obj = roundtrip(MeasurementEvidence, FIXTURES / "meas-camera-recording-UHD60-A0-sw123.yaml")
    fw = obj.provenance.runtime_sw_state.active_firmware
    assert fw["isp"] == "0x41"
    assert fw["dsp"] == "0x22"
    assert obj.provenance.sample_count == 10
    assert obj.provenance.confidence_level == 0.95


# ---------------------------------------------------------------------------
# Extra fields forbidden
# ---------------------------------------------------------------------------

def test_extra_fields_forbidden_sim():
    raw = load_yaml(FIXTURES / "sim-camera-recording-UHD60-A0-sw123.yaml")
    raw["unknown_field"] = "oops"
    with pytest.raises(ValidationError):
        SimulationEvidence.model_validate(raw)


def test_extra_fields_forbidden_meas():
    raw = load_yaml(FIXTURES / "meas-camera-recording-UHD60-A0-sw123.yaml")
    raw["ghost"] = True
    with pytest.raises(ValidationError):
        MeasurementEvidence.model_validate(raw)


# ---------------------------------------------------------------------------
# Sim fixture detailed assertions
# ---------------------------------------------------------------------------

def test_sim_resolution_result_structure():
    obj = roundtrip(SimulationEvidence, FIXTURES / "sim-camera-recording-UHD60-A0-sw123.yaml")
    rr = obj.resolution_result
    assert rr.overall_feasibility == OverallFeasibility.production_ready
    assert rr.violation_summary.total == 0
    assert "isp0" in rr.hw_resolution
    assert rr.hw_resolution["isp0"].matched_mode == "high_throughput"
    assert rr.sw_resolution.profile_ref == "sw-vendor-v1.2.3"
    checks = {fc.feature: fc.status for fc in rr.sw_resolution.required_features_check}
    assert checks["LLC_dynamic_allocation"] == "PASS"


def test_sim_ip_breakdown():
    obj = roundtrip(SimulationEvidence, FIXTURES / "sim-camera-recording-UHD60-A0-sw123.yaml")
    isp = next(b for b in obj.ip_breakdown if b.ip == "ip-isp-v12")
    assert isp.power_mW == 780
    subs = {s.sub: s.power_mW for s in isp.submodules}
    assert subs["ISP.TNR"] == 320
    assert subs["ISP.3AA0"] == 210
