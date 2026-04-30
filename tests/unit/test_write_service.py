from __future__ import annotations

from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.write.service import (
    build_import_bundle_diff,
    normalize_payload,
    normalize_import_bundle_payload,
    normalize_pipeline_patch_payload,
    validate_import_bundle,
    validate_pipeline_patch,
    validate_variant_overlay,
)


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
            category="codec",
            capabilities={
                "operating_modes": [
                    {"id": "normal"},
                    {"id": "high_throughput"},
                ]
            },
            yaml_sha256="test",
        )
        self.ip_isp = IpCatalog(
            id="ip-isp-v12",
            schema_version="2.2",
            category="camera",
            capabilities={},
            yaml_sha256="test",
        )
        self.ip_csis = IpCatalog(
            id="ip-csis-v8",
            schema_version="2.2",
            category="camera",
            capabilities={},
            yaml_sha256="test",
        )
        self.variant = ScenarioVariant(
            scenario_id="uc-camera-recording",
            id="existing",
        )
        self.project = Project(
            id="proj-A",
            schema_version="2.2",
            metadata_={"name": "Project A", "soc_ref": "soc-A"},
            yaml_sha256="test",
        )

    def query(self, model):
        if model is Scenario:
            return _Query([self.scenario])
        if model is ScenarioVariant:
            return _Query([self.variant])
        if model is Project:
            return _Query([self.project])
        if model is IpCatalog:
            return _Query([self.ip, self.ip_isp, self.ip_csis])
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


def _pipeline_patch_payload(patch):
    return {"scenario_ref": "uc-camera-recording", "patch": patch}


def test_normalize_pipeline_patch_defaults_optional_lists():
    normalized = normalize_pipeline_patch_payload(
        _pipeline_patch_payload(
            {
                "upsert_buffers": {
                    "ANALYSIS_BUF": {"format": "YUV420"},
                }
            }
        )
    )
    patch = normalized["patch"]
    assert normalized["scenario_ref"] == "uc-camera-recording"
    assert patch["add_nodes"] == []
    assert patch["add_edges"] == []
    assert patch["upsert_buffers"]["ANALYSIS_BUF"]["format"] == "YUV420"


def test_validate_pipeline_patch_accepts_buffer_and_m2m_edge():
    normalized = normalize_pipeline_patch_payload(
        _pipeline_patch_payload(
            {
                "upsert_buffers": {
                    "ANALYSIS_BUF": {"format": "YUV420"},
                },
                "add_edges": [
                    {"from": "isp0", "to": "mfc", "type": "M2M", "buffer": "ANALYSIS_BUF"},
                ],
            }
        )
    )
    issues = validate_pipeline_patch(_Db(), normalized)
    assert not any(issue.severity == "error" for issue in issues)


def test_validate_pipeline_patch_rejects_unknown_endpoint():
    normalized = normalize_pipeline_patch_payload(
        _pipeline_patch_payload(
            {
                "add_edges": [
                    {"from": "isp0", "to": "npu0", "type": "M2M", "buffer": "RECORD_BUF"},
                ],
            }
        )
    )
    issues = validate_pipeline_patch(_Db(), normalized)
    assert any(issue.code == "edge_target_not_found" for issue in issues)


def test_validate_pipeline_patch_rejects_otf_with_buffer():
    normalized = normalize_pipeline_patch_payload(
        _pipeline_patch_payload(
            {
                "add_edges": [
                    {"from": "csis0", "to": "isp0", "type": "OTF", "buffer": "RECORD_BUF"},
                ],
            }
        )
    )
    issues = validate_pipeline_patch(_Db(), normalized)
    assert any(issue.code == "otf_edge_must_not_have_buffer" for issue in issues)


def test_validate_pipeline_patch_rejects_variant_overlay_breakage():
    db = _Db()
    db.variant.node_configs = {"mfc": {"selected_mode": "normal"}}
    normalized = normalize_pipeline_patch_payload(
        _pipeline_patch_payload({"remove_nodes": ["mfc"]})
    )
    issues = validate_pipeline_patch(db, normalized)
    assert any(issue.code == "variant_overlay_impact" for issue in issues)


def _import_usecase_doc(**overrides):
    doc = {
        "id": "uc-camera-recording-imported",
        "schema_version": "2.2",
        "kind": "scenario.usecase",
        "project_ref": "proj-A",
        "metadata": {"name": "Imported Camera Recording", "category": ["camera"], "domain": ["camera"]},
        "pipeline": {
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
                "RECORD_BUF": {"format": "YUV420", "bitdepth": 10},
            },
        },
        "variants": [
            {
                "id": "FHD30-Imported",
                "severity": "medium",
                "design_conditions": {"resolution": "FHD", "fps": 30},
                "node_configs": {"mfc": {"selected_mode": "normal"}},
                "buffer_overrides": {"RECORD_BUF": {"format": "YUV420"}},
            }
        ],
    }
    doc.update(overrides)
    return doc


def test_normalize_import_bundle_accepts_import_report_and_documents():
    normalized = normalize_import_bundle_payload(
        {
            "documents": [_import_usecase_doc()],
            "import_report": {"ok": True, "generated": {"scenario_usecase": 1}, "messages": []},
        }
    )

    assert normalized["documents"][0]["kind"] == "scenario.usecase"
    assert normalized["import_report"]["generated"]["scenario_usecase"] == 1


def test_validate_import_bundle_accepts_canonical_usecase_doc():
    normalized = normalize_import_bundle_payload({"documents": [_import_usecase_doc()]})

    issues = validate_import_bundle(_Db(), normalized)

    assert issues == []


def test_validate_import_bundle_rejects_missing_import_ip_ref():
    doc = _import_usecase_doc()
    doc["pipeline"]["nodes"].append({"id": "npu0", "ip_ref": "ip-npu-v1"})
    normalized = normalize_import_bundle_payload({"documents": [doc]})

    issues = validate_import_bundle(_Db(), normalized)

    assert any(issue.code == "import_ip_ref_not_found" for issue in issues)


def test_validate_import_bundle_rejects_missing_edge_buffer():
    doc = _import_usecase_doc()
    doc["pipeline"]["edges"].append({"from": "isp0", "to": "mfc", "type": "M2M", "buffer": "MISSING_BUF"})
    normalized = normalize_import_bundle_payload({"documents": [doc]})

    issues = validate_import_bundle(_Db(), normalized)

    assert any(issue.code == "import_edge_buffer_not_found" for issue in issues)


def test_validate_import_bundle_accepts_votf_edge_without_buffer():
    doc = _import_usecase_doc()
    doc["pipeline"]["edges"].append({"from": "csis0", "to": "isp0", "type": "vOTF"})
    normalized = normalize_import_bundle_payload({"documents": [doc]})

    issues = validate_import_bundle(_Db(), normalized)

    assert issues == []


def test_validate_import_bundle_rejects_import_report_errors():
    normalized = normalize_import_bundle_payload(
        {
            "documents": [_import_usecase_doc()],
            "import_report": {
                "ok": False,
                "messages": [{"level": "error", "code": "legacy_parse_failed", "message": "bad yaml"}],
            },
        }
    )

    issues = validate_import_bundle(_Db(), normalized)

    assert any(issue.code == "import_report_error" for issue in issues)


def test_import_bundle_diff_reports_document_and_variant_impact():
    db = _Db()
    db.scenario.id = "uc-camera-recording-imported"
    db.variant.scenario_id = "uc-camera-recording-imported"
    db.variant.id = "OldVariant"
    normalized = normalize_import_bundle_payload(
        {
            "documents": [_import_usecase_doc()],
            "import_report": {"ok": True, "generated": {"validated_yaml": 1}, "messages": [{"level": "warning"}]},
        }
    )

    diff = build_import_bundle_diff(db, normalized)

    assert diff.target_id == "uc-camera-recording-imported"
    assert diff.operation == "update"
    assert diff.impact["import_report"]["messages_by_level"]["warning"] == 1
    assert diff.impact["scenario_impacts"][0]["variants_added"] == ["FHD30-Imported"]
    assert diff.impact["scenario_impacts"][0]["variants_removed"] == ["OldVariant"]
