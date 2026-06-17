from __future__ import annotations

from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.etl.validate_loaded import validate_loaded_db


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Db:
    def __init__(self):
        self.project = Project(id="proj-A", schema_version="2.2", metadata_={}, yaml_sha256="sha")
        self.ip = IpCatalog(
            id="ip-isp-v1",
            schema_version="2.2",
            category="ISP",
            hierarchy={},
            capabilities={"operating_modes": [{"id": "normal"}]},
            yaml_sha256="sha",
        )
        self.scenario = Scenario(
            id="uc-camera-a",
            schema_version="2.2",
            project_ref="proj-A",
            metadata_={},
            pipeline={
                "nodes": [{"id": "isp", "ip_ref": "ip-isp-v1"}],
                "edges": [],
                "buffers": {"REC": {"format": "YUV420"}},
            },
            yaml_sha256="sha",
        )
        self.variant = ScenarioVariant(scenario_id="uc-camera-a", id="v1")
        self.variant.node_configs = {}
        self.variant.buffer_overrides = {}
        self.variant.topology_patch = {}

    def query(self, model):
        rows = {
            Project: [self.project],
            IpCatalog: [self.ip],
            Scenario: [self.scenario],
            ScenarioVariant: [self.variant],
        }.get(model, [])
        return _Query(rows)


def test_validate_loaded_db_rejects_variant_overlay_refs_missing_from_base():
    db = _Db()
    db.variant.node_configs = {"missing-node": {}}
    db.variant.buffer_overrides = {"MISSING_BUF": {"format": "P010"}}

    report = validate_loaded_db(db)

    assert any("node_configs references missing node" in item for item in report.errors)
    assert any("buffer_overrides references missing buffer" in item for item in report.errors)


def test_validate_loaded_db_rejects_unsupported_selected_mode():
    db = _Db()
    db.variant.node_configs = {"isp": {"selected_mode": "turbo"}}

    report = validate_loaded_db(db)

    assert any("selected_mode 'turbo' is not supported" in item for item in report.errors)


def test_validate_loaded_db_allows_topology_patch_added_node_config():
    db = _Db()
    db.variant.topology_patch = {"add_nodes": [{"id": "sw_eis", "node_type": "SW_TASK"}]}
    db.variant.node_configs = {"sw_eis": {"kind": "sw_task"}}

    report = validate_loaded_db(db)

    assert report.errors == []


def test_validate_loaded_db_warns_for_unqualified_canonical_scenario_id():
    db = _Db()
    db.scenario.id = "uc-camera"
    db.scenario.metadata_ = {"canonical_usecase": "camera"}
    db.variant.scenario_id = "uc-camera"

    report = validate_loaded_db(db)

    assert any("project-qualified" in item for item in report.warnings)
