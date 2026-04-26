from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scenario_db.models.capability.hw import IpCatalog, IpHierarchy, SocPlatform
from scenario_db.models.capability.sw import SwComponent, SwProfile
from scenario_db.models.common import (
    DocumentId,
    InstanceId,
    SchemaVersion,
    Severity,
    SourceType,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def roundtrip(model_cls, path: Path, **dump_kwargs):
    """Load YAML → parse model → re-serialise → re-parse. Both must be equal.

    Pass dump_kwargs (e.g. by_alias=True) only when the model uses Field aliases
    that must survive round-trip serialisation (e.g. PipelineEdge.from_).
    """
    raw = load_yaml(path)
    obj = model_cls.model_validate(raw)
    serialised = obj.model_dump(exclude_none=True, **dump_kwargs)
    obj2 = model_cls.model_validate(serialised)
    assert obj == obj2
    return obj


# ---------------------------------------------------------------------------
# SchemaVersion
# ---------------------------------------------------------------------------

from pydantic import BaseModel, ConfigDict

class _SV(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: SchemaVersion


@pytest.mark.parametrize("ver", ["2.2", "1.0", "3.1.4"])
def test_schema_version_valid(ver):
    assert _SV(v=ver).v == ver


@pytest.mark.parametrize("bad", ["2", "v2.2", "2.2.2.2", ""])
def test_schema_version_invalid(bad):
    with pytest.raises(ValidationError):
        _SV(v=bad)


# ---------------------------------------------------------------------------
# DocumentId
# ---------------------------------------------------------------------------

class _DI(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: DocumentId


@pytest.mark.parametrize("doc_id", [
    "ip-isp-v12",
    "sw-vendor-v1.2.3",
    "hal-cam-v4.5",
    "kernel-6.1.50-android15",
    "fw-isp-0x41",
    "soc-exynos2500",
    "iss-LLC-thrashing-0221",
    "rule-feasibility-check",
])
def test_document_id_valid(doc_id):
    assert _DI(id=doc_id).id == doc_id


@pytest.mark.parametrize("bad", [
    "ISP-v12",           # uppercase prefix
    "unknown-thing",     # unknown prefix
    "ip-",               # no suffix
    "",
    "ip_isp_v12",        # underscores instead of hyphens
    "ip isp v12",        # spaces
    "ip-@isp",           # special chars
])
def test_document_id_invalid(bad):
    with pytest.raises(ValidationError):
        _DI(id=bad)


# ---------------------------------------------------------------------------
# InstanceId
# ---------------------------------------------------------------------------

class _II(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: InstanceId


@pytest.mark.parametrize("inst_id", ["ISP", "ISP.TNR", "ISP.3AA0", "MFC", "DPU"])
def test_instance_id_valid(inst_id):
    assert _II(id=inst_id).id == inst_id


@pytest.mark.parametrize("bad", ["isp.tnr", "ISP.", ".TNR", "ISP TNR", ""])
def test_instance_id_invalid(bad):
    with pytest.raises(ValidationError):
        _II(id=bad)


# ---------------------------------------------------------------------------
# Severity / SourceType enums
# ---------------------------------------------------------------------------

def test_severity_values():
    assert set(Severity) == {"light", "medium", "heavy", "critical"}


def test_source_type_values():
    assert set(SourceType) == {"calculated", "estimated", "measured"}


# ---------------------------------------------------------------------------
# IpHierarchy validator
# ---------------------------------------------------------------------------

def test_hierarchy_simple_no_submodules():
    h = IpHierarchy(type="simple")
    assert h.submodules is None


def test_hierarchy_simple_with_submodules_forbidden():
    with pytest.raises(ValidationError, match="simple hierarchy"):
        IpHierarchy(type="simple", submodules=[
            {"ref": "sub-3aa-v4", "instance_id": "ISP.3AA0"}
        ])


def test_hierarchy_composite_requires_submodules():
    with pytest.raises(ValidationError, match="composite hierarchy"):
        IpHierarchy(type="composite")


def test_hierarchy_composite_ok():
    h = IpHierarchy(type="composite", submodules=[
        {"ref": "sub-3aa-v4", "instance_id": "ISP.3AA0"}
    ])
    assert len(h.submodules) == 1


# ---------------------------------------------------------------------------
# Extra fields forbidden
# ---------------------------------------------------------------------------

def test_extra_fields_forbidden_ipcatalog():
    raw = load_yaml(FIXTURES / "hw" / "ip-isp-v12.yaml")
    raw["unexpected_field"] = "oops"
    with pytest.raises(ValidationError):
        IpCatalog.model_validate(raw)


def test_extra_fields_forbidden_swprofile():
    raw = load_yaml(FIXTURES / "sw" / "sw-vendor-v1.2.3.yaml")
    raw["ghost_field"] = True
    with pytest.raises(ValidationError):
        SwProfile.model_validate(raw)


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------

def test_ip_catalog_roundtrip():
    obj = roundtrip(IpCatalog, FIXTURES / "hw" / "ip-isp-v12.yaml")
    assert obj.id == "ip-isp-v12"
    assert obj.kind == "ip"
    assert obj.hierarchy.type == "composite"
    assert len(obj.hierarchy.submodules) == 3
    modes = {m.id for m in obj.capabilities.operating_modes}
    assert modes == {"normal", "low_power", "high_throughput"}
    assert obj.capabilities.supported_features.bitdepth == [8, 10, 12]


def test_sw_profile_roundtrip():
    obj = roundtrip(SwProfile, FIXTURES / "sw" / "sw-vendor-v1.2.3.yaml")
    assert obj.id == "sw-vendor-v1.2.3"
    assert obj.kind == "sw_profile"
    assert obj.metadata.baseline_family == "vendor"
    assert obj.feature_flags["LLC_dynamic_allocation"] == "enabled"
    assert obj.feature_flags["preview_buffer_count"] == 8
    assert obj.compatibility.replaces == "sw-vendor-v1.2.2"
    assert len(obj.components.hal) == 3
    hal_domains = {h.domain for h in obj.components.hal}
    assert hal_domains == {"camera", "codec", "display"}


def test_sw_component_hal_roundtrip():
    obj = roundtrip(SwComponent, FIXTURES / "sw" / "hal-cam-v4.5.yaml")
    assert obj.id == "hal-cam-v4.5"
    assert obj.kind == "sw_component"
    assert obj.category == "hal"
    assert "android.hardware.camera.device@3.7" in obj.required_interfaces
    assert obj.hw_bindings.required_ips == ["ip-isp-v12", "ip-csis-v8"]
    assert obj.performance_notes["preview_latency_overhead_ms"] == 2.5


# ---------------------------------------------------------------------------
# Semantic validation
# ---------------------------------------------------------------------------

def test_sw_profile_feature_flags_type_safety():
    """feature_flags must reject non-bool/str/int values."""
    raw = load_yaml(FIXTURES / "sw" / "sw-vendor-v1.2.3.yaml")
    raw["feature_flags"]["bad_flag"] = [1, 2, 3]   # list is not allowed
    with pytest.raises(ValidationError):
        SwProfile.model_validate(raw)


def test_submodule_instance_id_must_be_uppercase():
    with pytest.raises(ValidationError):
        IpHierarchy(type="composite", submodules=[
            {"ref": "sub-3aa-v4", "instance_id": "isp.tnr"}   # lowercase → invalid InstanceId
        ])
