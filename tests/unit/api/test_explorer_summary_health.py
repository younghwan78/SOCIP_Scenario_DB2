from __future__ import annotations

from scenario_db.api.routers.explorer import explorer_summary, import_health
from scenario_db.db.models.capability import IpCatalog, SocPlatform, SwProfile
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.write import WriteBatch


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *criteria):
        return self

    def order_by(self, *criteria):
        return self

    def limit(self, value):
        return self

    def offset(self, value):
        return self

    def all(self):
        return list(self.rows)

    def count(self):
        return len(self.rows)


class _Session:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        # Column queries (db.query(Model.col)) resolve to the owning class.
        model = getattr(model, "class_", model)
        return _Query(self.rows.get(model, []))


def _project(metadata: dict) -> Project:
    return Project(
        id="proj-A",
        schema_version="2.2",
        metadata_=metadata,
        yaml_sha256="sha",
    )


def _scenario(metadata: dict) -> Scenario:
    return Scenario(
        id="uc-camera",
        schema_version="2.2",
        project_ref="proj-A",
        metadata_=metadata,
        pipeline={"nodes": [], "edges": []},
        yaml_sha256="sha",
    )


def test_summary_filters_echo_does_not_leak_loop_category():
    """Regression: the category loop variable must not shadow the request filter."""
    session = _Session(
        {
            Project: [_project({"soc_ref": "soc-A", "board_type": "ERD"})],
            Scenario: [_scenario({"category": ["camera"]})],
            ScenarioVariant: [ScenarioVariant(scenario_id="uc-camera", id="v1", severity="medium")],
            SocPlatform: [],
            IpCatalog: [],
            SwProfile: [],
            WriteBatch: [],
        }
    )

    response = explorer_summary(
        soc_ref=None,
        board_type=None,
        project_ref=None,
        category=None,
        domain=None,
        scenario_id=None,
        severity=None,
        db=session,
    )

    # No category filter was requested, so the echo must not contain one.
    assert "category" not in response.filters
    assert {item.key: item.count for item in response.category_counts} == {"camera": 1}


def test_summary_filters_echo_preserves_requested_category():
    session = _Session(
        {
            Project: [_project({"soc_ref": "soc-A", "board_type": "ERD"})],
            Scenario: [_scenario({"category": ["camera", "video"]})],
            ScenarioVariant: [],
            SocPlatform: [],
            IpCatalog: [],
            SwProfile: [],
            WriteBatch: [],
        }
    )

    response = explorer_summary(
        soc_ref=None,
        board_type=None,
        project_ref=None,
        category=["camera"],
        domain=None,
        scenario_id=None,
        severity=None,
        db=session,
    )

    assert response.filters.get("category") == ["camera"]


def test_import_health_counts_reflect_full_result_before_truncation():
    """Regression: issue_counts/total must be computed before the limit cut."""
    session = _Session(
        {
            Project: [
                _project(
                    {
                        "soc_ref": "soc-missing",
                        "sensor_module_ref": "ip-missing-sensor",
                        "display_module_ref": "ip-missing-panel",
                    }
                )
            ],
            Scenario: [],
            ScenarioVariant: [],
            SocPlatform: [],
            IpCatalog: [],
            SwProfile: [],
            WriteBatch: [],
        }
    )

    response = import_health(
        soc_ref=None,
        board_type=None,
        project_ref=None,
        category=None,
        domain=None,
        scenario_id=None,
        severity=None,
        issue_severity=None,
        code=None,
        document_kind=None,
        document_id=None,
        limit=1,
        db=session,
    )

    assert len(response.issues) == 1
    assert response.total_issue_count == 3
    assert response.truncated is True
    assert sum(response.issue_counts.values()) == 3


def test_import_health_reports_data_flow_cycle():
    scenario = _scenario({"category": ["camera"]})
    scenario.pipeline = {
        "nodes": [{"id": "a"}, {"id": "b"}],
        "edges": [
            {"from": "a", "to": "b", "type": "OTF"},
            {"from": "b", "to": "a", "type": "M2M", "buffer": "BUF"},
        ],
        "buffers": {"BUF": {"format": "YUV420"}},
    }
    session = _Session(
        {
            Project: [_project({})],
            Scenario: [scenario],
            ScenarioVariant: [ScenarioVariant(scenario_id="uc-camera", id="v1", severity="medium")],
            SocPlatform: [],
            IpCatalog: [],
            SwProfile: [],
            WriteBatch: [],
        }
    )

    response = import_health(
        soc_ref=None,
        board_type=None,
        project_ref=None,
        category=None,
        domain=None,
        scenario_id=None,
        severity=None,
        issue_severity=None,
        code=["scenario_pipeline_cycle"],
        document_kind=None,
        document_id=None,
        limit=50,
        db=session,
    )

    cycle_issues = [issue for issue in response.issues if issue.code == "scenario_pipeline_cycle"]
    assert len(cycle_issues) == 1
    assert cycle_issues[0].document_id == "uc-camera"
    assert "a" in cycle_issues[0].message and "b" in cycle_issues[0].message


def test_import_health_reports_variant_overlay_integrity_issues():
    scenario = _scenario({"category": ["camera"]})
    scenario.pipeline = {
        "nodes": [{"id": "isp", "ip_ref": "ip-isp-v1"}],
        "edges": [],
        "buffers": {"REC": {"format": "YUV420"}},
    }
    variant = ScenarioVariant(scenario_id="uc-camera", id="v1", severity="medium")
    variant.node_configs = {
        "missing-node": {},
        "isp": {"selected_mode": "turbo"},
    }
    variant.buffer_overrides = {"MISSING_BUF": {"format": "P010"}}
    ip = IpCatalog(
        id="ip-isp-v1",
        schema_version="2.2",
        category="ISP",
        hierarchy={},
        capabilities={"operating_modes": [{"id": "normal"}]},
        yaml_sha256="sha",
    )
    session = _Session(
        {
            Project: [_project({})],
            Scenario: [scenario],
            ScenarioVariant: [variant],
            SocPlatform: [],
            IpCatalog: [ip],
            SwProfile: [],
            WriteBatch: [],
        }
    )

    response = import_health(
        soc_ref=None,
        board_type=None,
        project_ref=None,
        category=None,
        domain=None,
        scenario_id=None,
        severity=None,
        issue_severity=None,
        code=None,
        document_kind=None,
        document_id=None,
        limit=50,
        db=session,
    )

    codes = {issue.code for issue in response.issues}
    assert "unknown_node_config" in codes
    assert "unsupported_selected_mode" in codes
    assert "unknown_buffer_override" in codes


def test_import_health_warns_for_unqualified_canonical_scenario_id():
    scenario = _scenario(
        {
            "name": "Camera Recording",
            "category": ["camera"],
            "canonical_usecase": "camera-recording",
        }
    )
    scenario.id = "uc-camera-recording"
    variant = ScenarioVariant(scenario_id="uc-camera-recording", id="v1", severity="medium")
    session = _Session(
        {
            Project: [_project({})],
            Scenario: [scenario],
            ScenarioVariant: [variant],
            SocPlatform: [],
            IpCatalog: [],
            SwProfile: [],
            WriteBatch: [],
        }
    )

    response = import_health(
        soc_ref=None,
        board_type=None,
        project_ref=None,
        category=None,
        domain=None,
        scenario_id=None,
        severity=None,
        issue_severity=None,
        code=["scenario_id_not_project_qualified"],
        document_kind=None,
        document_id=None,
        limit=50,
        db=session,
    )

    assert len(response.issues) == 1
    assert response.issues[0].severity == "warning"
    assert "project-qualified" in response.issues[0].message
