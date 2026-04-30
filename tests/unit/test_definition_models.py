from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scenario_db.models.definition.project import Project
from scenario_db.models.definition.usecase import (
    DesignAxis,
    EdgeType,
    IpRequirementSpec,
    Pipeline,
    PipelineEdge,
    PipelineNode,
    Usecase,
    Variant,
    ViolationAction,
    ViolationClassification,
    ViolationPolicy,
    PerRequirementPolicy,
    OverallPolicy,
    SwRequirements,
)
from scenario_db.models.common import Severity

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers (same interface as test_capability_models.py)
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
# Project
# ---------------------------------------------------------------------------

def test_project_roundtrip():
    obj = roundtrip(Project, FIXTURES / "definition" / "proj-A-exynos2500.yaml")
    assert obj.id == "proj-A-exynos2500"
    assert obj.kind == "project"
    assert obj.metadata.soc_ref == "soc-exynos2500"
    assert obj.globals.default_sw_profile_ref == "sw-vendor-v1.2.3"
    assert len(obj.globals.tested_sw_profiles) == 3


def test_project_metadata_accepts_board_form_factor_fields():
    obj = Project.model_validate(
        {
            "id": "proj-thetis-erd",
            "schema_version": "1.0",
            "kind": "project",
            "metadata": {
                "name": "Thetis ERD",
                "soc_ref": "soc-exynos2600",
                "board_type": "ERD",
                "board_name": "internal-dev-board",
                "sensor_module_ref": "sensor-hp2",
                "display_module_ref": "display-amoled-qhd",
                "default_sw_profile_ref": "sw-vendor-v1.2.3",
            },
        }
    )
    assert obj.metadata.board_type == "ERD"
    assert obj.metadata.sensor_module_ref == "sensor-hp2"


def test_extra_fields_forbidden_project():
    raw = load_yaml(FIXTURES / "definition" / "proj-A-exynos2500.yaml")
    raw["unexpected"] = "oops"
    with pytest.raises(ValidationError):
        Project.model_validate(raw)


# ---------------------------------------------------------------------------
# Usecase — round-trip (by_alias=True for PipelineEdge.from_)
# ---------------------------------------------------------------------------

def test_usecase_roundtrip():
    obj = roundtrip(
        Usecase,
        FIXTURES / "definition" / "uc-camera-recording.yaml",
        by_alias=True,
    )
    assert obj.id == "uc-camera-recording"
    assert obj.kind == "scenario.usecase"
    assert obj.project_ref == "proj-A-exynos2500"
    assert len(obj.pipeline.nodes) == 5
    assert len(obj.pipeline.edges) == 3
    assert len(obj.design_axes) == 5
    assert len(obj.variants) == 3


def test_extra_fields_forbidden_usecase():
    raw = load_yaml(FIXTURES / "definition" / "uc-camera-recording.yaml")
    raw["ghost"] = True
    with pytest.raises(ValidationError):
        Usecase.model_validate(raw)


# ---------------------------------------------------------------------------
# Pipeline — edge alias & graph integrity
# ---------------------------------------------------------------------------

def test_pipeline_edge_from_alias():
    """YAML 'from:' key maps to Python field 'from_'."""
    edge = PipelineEdge.model_validate({"from": "csis0", "to": "isp0", "type": "OTF"})
    assert edge.from_ == "csis0"
    assert edge.to == "isp0"


def test_pipeline_edge_roundtrip_preserves_from_key():
    """model_dump(by_alias=True) must emit 'from', not 'from_'."""
    edge = PipelineEdge.model_validate({"from": "csis0", "to": "isp0", "type": "OTF"})
    dumped = edge.model_dump(by_alias=True, exclude_none=True)
    assert "from" in dumped
    assert "from_" not in dumped


def test_pipeline_edge_invalid_node_ref():
    """Edge referencing a non-existent node must raise ValidationError."""
    with pytest.raises(ValidationError, match="not found in nodes"):
        Pipeline.model_validate({
            "nodes": [
                {"id": "isp0", "ip_ref": "ip-isp-v12"},
            ],
            "edges": [
                {"from": "ghost_node", "to": "isp0", "type": "OTF"},
            ],
        })


def test_pipeline_edge_target_not_found():
    with pytest.raises(ValidationError, match="not found in nodes"):
        Pipeline.model_validate({
            "nodes": [{"id": "isp0", "ip_ref": "ip-isp-v12"}],
            "edges": [{"from": "isp0", "to": "nowhere", "type": "M2M"}],
        })


def test_pipeline_valid():
    p = Pipeline.model_validate({
        "nodes": [
            {"id": "a", "ip_ref": "ip-isp-v12"},
            {"id": "b", "ip_ref": "ip-mfc-v14"},
        ],
        "edges": [{"from": "a", "to": "b", "type": "M2M"}],
    })
    assert len(p.edges) == 1


# ---------------------------------------------------------------------------
# ViolationPolicy enums
# ---------------------------------------------------------------------------

def test_violation_classification_enum():
    assert set(ViolationClassification) == {"production", "exploration", "research"}


def test_violation_action_enum():
    assert set(ViolationAction) == {
        "FAIL_FAST", "WARN_AND_CAP", "WARN_AND_EMULATE", "SKIP_AND_LOG", "DEFAULT_TO"
    }


# ---------------------------------------------------------------------------
# IpRequirementSpec — extra="allow"
# ---------------------------------------------------------------------------

def test_ip_requirement_extra_fields_allowed():
    """extra="allow": IP-specific unknown fields must not raise."""
    spec = IpRequirementSpec.model_validate({
        "required_throughput_mpps": 498,
        "required_bitdepth": 10,
        "custom_isp_field": "some_value",   # extra field — allowed
    })
    assert spec.required_throughput_mpps == 498
    assert spec.model_extra["custom_isp_field"] == "some_value"


def test_ip_requirement_known_fields():
    spec = IpRequirementSpec.model_validate({
        "required_codec": "H.265",
        "required_level": "5.1",
    })
    assert spec.required_codec == "H.265"
    assert spec.required_level == "5.1"


# ---------------------------------------------------------------------------
# Variant
# ---------------------------------------------------------------------------

def test_variant_id_is_freeform():
    """Variant id must NOT be constrained to DocumentId format."""
    v = Variant.model_validate({
        "id": "UHD60-HDR10-H265",   # no prefix like "uc-" — must work
        "severity": "heavy",
    })
    assert v.id == "UHD60-HDR10-H265"


def test_derived_variant_parses():
    obj = roundtrip(
        Usecase,
        FIXTURES / "definition" / "uc-camera-recording.yaml",
        by_alias=True,
    )
    derived = next(v for v in obj.variants if v.derived_from_variant)
    assert derived.id == "UHD60-HDR10-sustained-10min"
    assert derived.derived_from_variant == "UHD60-HDR10-H265"


def test_variant_production_violation_policy():
    obj = roundtrip(
        Usecase,
        FIXTURES / "definition" / "uc-camera-recording.yaml",
        by_alias=True,
    )
    prod = next(v for v in obj.variants if v.id == "UHD60-HDR10-H265")
    assert prod.violation_policy.classification == ViolationClassification.production
    assert prod.violation_policy.per_requirement["default"].action == ViolationAction.FAIL_FAST
    assert prod.violation_policy.overall.if_any_fail == "abort_simulation"


def test_variant_exploration_violation_policy():
    obj = roundtrip(
        Usecase,
        FIXTURES / "definition" / "uc-camera-recording.yaml",
        by_alias=True,
    )
    expl = next(v for v in obj.variants if "exploration" in v.id)
    assert expl.violation_policy.classification == ViolationClassification.exploration
    cap_policy = expl.violation_policy.per_requirement["isp0.required_throughput_mpps"]
    assert cap_policy.action == ViolationAction.WARN_AND_CAP
    assert cap_policy.report_gap is True


# ---------------------------------------------------------------------------
# Inheritance cycle detection
# ---------------------------------------------------------------------------

def test_variant_inheritance_cycle_detection():
    """A → B → A circular chain must raise ValidationError."""
    base_raw = load_yaml(FIXTURES / "definition" / "uc-camera-recording.yaml")
    # Inject a cycle: UHD60-HDR10-H265 derives from sustained-10min which derives from it
    base_raw["variants"] = [
        {"id": "A", "severity": "heavy", "derived_from_variant": "B"},
        {"id": "B", "severity": "heavy", "derived_from_variant": "A"},
    ]
    with pytest.raises(ValidationError, match="Circular inheritance"):
        Usecase.model_validate(base_raw)


# ---------------------------------------------------------------------------
# ViolationPolicy dotted-path node reference
# ---------------------------------------------------------------------------

def test_violation_policy_invalid_node_ref():
    """per_requirement key referencing unknown pipeline node must fail."""
    base_raw = load_yaml(FIXTURES / "definition" / "uc-camera-recording.yaml")
    base_raw["variants"] = [
        {
            "id": "bad-variant",
            "severity": "heavy",
            "violation_policy": {
                "classification": "production",
                "per_requirement": {
                    "ghost_node.some_field": {"action": "FAIL_FAST"},
                },
            },
        }
    ]
    with pytest.raises(ValidationError, match="unknown pipeline node 'ghost_node'"):
        Usecase.model_validate(base_raw)


def test_violation_policy_default_key_allowed():
    """'default' key in per_requirement must NOT trigger node validation."""
    base_raw = load_yaml(FIXTURES / "definition" / "uc-camera-recording.yaml")
    # Just parse the fixture — it already has a 'default' key
    obj = Usecase.model_validate(base_raw)
    prod = next(v for v in obj.variants if v.id == "UHD60-HDR10-H265")
    assert "default" in prod.violation_policy.per_requirement


# ---------------------------------------------------------------------------
# SW Requirements
# ---------------------------------------------------------------------------

def test_sw_required_features_list_format():
    obj = roundtrip(
        Usecase,
        FIXTURES / "definition" / "uc-camera-recording.yaml",
        by_alias=True,
    )
    prod = next(v for v in obj.variants if v.id == "UHD60-HDR10-H265")
    features = prod.sw_requirements.required_features
    assert isinstance(features, list)
    assert all(isinstance(f, dict) and len(f) == 1 for f in features)
    keys = [list(f.keys())[0] for f in features]
    assert "LLC_dynamic_allocation" in keys
    assert "MFC_hwae" in keys


# ---------------------------------------------------------------------------
# DesignAxis & SizeProfile
# ---------------------------------------------------------------------------

def test_design_axes_parsed():
    obj = roundtrip(
        Usecase,
        FIXTURES / "definition" / "uc-camera-recording.yaml",
        by_alias=True,
    )
    axis_names = {a.name for a in obj.design_axes}
    assert axis_names == {"resolution", "fps", "codec", "hdr", "concurrency"}


def test_size_profile_parsed():
    obj = roundtrip(
        Usecase,
        FIXTURES / "definition" / "uc-camera-recording.yaml",
        by_alias=True,
    )
    assert obj.size_profile.anchors["sensor_full"] == "4000x3000"


def test_view_fixture_graphs_are_present():
    obj = roundtrip(
        Usecase,
        FIXTURES / "definition" / "uc-camera-recording.yaml",
        by_alias=True,
    )

    assert obj.pipeline.buffers["RECORD_BUF"]["placement"]["llc_allocated"] is True
    assert obj.pipeline.architecture_graph["memory_below_hw"] is True
    assert obj.pipeline.task_graph["layout"] == "task-topology"
    assert len(obj.pipeline.task_graph["nodes"]) >= 10
    assert obj.pipeline.level1_graph["nodes_from_task_graph"] is True


# ---------------------------------------------------------------------------
# Parametric sweeps & references
# ---------------------------------------------------------------------------

def test_parametric_sweeps_parsed():
    obj = roundtrip(
        Usecase,
        FIXTURES / "definition" / "uc-camera-recording.yaml",
        by_alias=True,
    )
    assert len(obj.parametric_sweeps) == 1
    sweep = obj.parametric_sweeps[0]
    assert sweep.id == "zoom_sweep"
    assert sweep.values == [1.0, 0.5, 0.25, 0.1]


def test_references_known_issues():
    obj = roundtrip(
        Usecase,
        FIXTURES / "definition" / "uc-camera-recording.yaml",
        by_alias=True,
    )
    assert "iss-LLC-thrashing-0221" in obj.references.known_issues
