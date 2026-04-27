from __future__ import annotations

from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.write.service import normalize_payload, validate_variant_overlay


class _Query:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter_by(self, **kwargs):
        def matches(row):
            return all(getattr(row, key) == value for key, value in kwargs.items())

        return _Query([row for row in self._rows if matches(row)])

    def one_or_none(self):
        if not self._rows:
            return None
        if len(self._rows) > 1:
            raise AssertionError("fake query expected at most one row")
        return self._rows[0]

    def all(self):
        return self._rows


class _Db:
    def __init__(self):
        self.scenario = Scenario(
            id="uc-camera-recording",
            schema_version="2.2",
            project_ref="proj-A",
            metadata_={"name": "Camera Recording"},
            pipeline={
                "nodes": [
                    {"id": "csis0", "ip_ref": "ip-csis-v8"},
                    {"id": "isp0", "ip_ref": "ip-isp-v12"},
                    {"id": "mfc", "ip_ref": "ip-mfc-v14"},
                ],
                "edges": [
                    {"from": "csis0", "to": "isp0", "type": "OTF"},
                    {"from": "isp0", "to": "mfc", "type": "M2M", "buffer": "RECORD_BUF"},
                ],
                "buffers": {
                    "RECORD_BUF": {"format": "YUV420"},
                },
            },
            yaml_sha256="test",
        )
        self.ip = IpCatalog(
            id="ip-mfc-v14",
            schema_version="2.2",
            capabilities={
                "operating_modes": [
                    {"id": "normal"},
                    {"id": "high_throughput"},
                ]
            },
            yaml_sha256="test",
        )
        self.variant = ScenarioVariant(
            scenario_id="uc-camera-recording",
            id="existing",
        )

    def query(self, model):
        if model is Scenario:
            return _Query([self.scenario])
        if model is ScenarioVariant:
            return _Query([self.variant])
        if model is IpCatalog:
            return _Query([self.ip])
        return _Query([])


def _payload(**variant_overrides):
    variant = {
        "id": "FHD30-write-test",
        "severity": "medium",
        "design_conditions": {"resolution": "FHD", "fps": 30},
        "node_configs": {
            "mfc": {"selected_mode": "normal"},
        },
        "buffer_overrides": {
            "RECORD_BUF": {
                "format": "YUV420",
                "compression": "SBWC_v4",
                "placement": {"llc_allocated": True},
            }
        },
    }
    variant.update(variant_overrides)
    return {"scenario_ref": "uc-camera-recording", "variant": variant}


def test_normalize_variant_overlay_defaults_optional_fields():
    normalized = normalize_payload(_payload())
    variant = normalized["variant"]
    assert normalized["scenario_ref"] == "uc-camera-recording"
    assert variant["routing_switch"] == {}
    assert variant["topology_patch"] == {}
    assert variant["tags"] == []


def test_validate_variant_overlay_accepts_supported_mode_and_buffer():
    issues = validate_variant_overlay(_Db(), normalize_payload(_payload()))
    assert issues == []


def test_validate_variant_overlay_rejects_unknown_disabled_edge():
    issues = validate_variant_overlay(
        _Db(),
        normalize_payload(
            _payload(routing_switch={"disabled_edges": [{"from": "isp0", "to": "dpu"}]})
        ),
    )
    assert any(issue.code == "unknown_disabled_edge" for issue in issues)


def test_validate_variant_overlay_rejects_hw_topology_injection():
    issues = validate_variant_overlay(
        _Db(),
        normalize_payload(
            _payload(
                topology_patch={
                    "add_nodes": [{"id": "npu0", "node_type": "HW", "ip_ref": "ip-npu-v1"}],
                    "add_edges": [{"from": "isp0", "to": "npu0", "type": "M2M"}],
                }
            )
        ),
    )
    assert any(issue.code == "hw_node_injection_forbidden" for issue in issues)


def test_validate_variant_overlay_rejects_unsupported_selected_mode():
    issues = validate_variant_overlay(
        _Db(),
        normalize_payload(_payload(node_configs={"mfc": {"selected_mode": "low_power"}})),
    )
    assert any(issue.code == "unsupported_selected_mode" for issue in issues)


def test_validate_variant_overlay_rejects_compression_inside_placement():
    issues = validate_variant_overlay(
        _Db(),
        normalize_payload(
            _payload(
                buffer_overrides={
                    "RECORD_BUF": {
                        "placement": {
                            "llc_allocated": True,
                            "compression": "SBWC_v4",
                        }
                    }
                }
            )
        ),
    )
    assert any(issue.code == "compression_in_placement" for issue in issues)
