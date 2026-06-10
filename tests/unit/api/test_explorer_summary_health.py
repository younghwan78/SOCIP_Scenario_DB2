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
