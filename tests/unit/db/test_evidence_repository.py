from __future__ import annotations

from pathlib import Path

import yaml

from scenario_db.db.repositories.evidence import upsert_simulation_evidence
from scenario_db.models.evidence.simulation import SimulationEvidence

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "evidence"


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        return self

    def one_or_none(self):
        matches = [
            row
            for row in self.rows.values()
            if all(getattr(row, key) == value for key, value in self.filters.items())
        ]
        assert len(matches) <= 1
        return matches[0] if matches else None


class _Session:
    def __init__(self):
        self.rows = {}

    def query(self, model):
        return _Query(self.rows)

    def add(self, row):
        self.rows[row.id] = row


def _load(name: str) -> dict:
    return yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))


def test_upsert_simulation_evidence_stores_empty_topology_order_as_null_and_trace_as_dict():
    raw = _load("sim-camera-recording-UHD60-EVT0-sw123.yaml")
    raw["topology_order"] = []
    raw["calculation_trace"] = {
        "kpi": {
            "total_power_mw": {
                "formula": "manual seed",
                "inputs": {"source": "test"},
                "result": raw["kpi"]["total_power_mw"],
            }
        }
    }
    evidence = SimulationEvidence.model_validate(raw)
    db = _Session()

    row = upsert_simulation_evidence(db, evidence, yaml_sha256="sha-sim")

    assert row.topology_order is None
    assert row.calculation_trace == raw["calculation_trace"]


def test_upsert_simulation_evidence_preserves_exported_artifacts_on_rerun():
    raw = _load("sim-camera-recording-UHD60-EVT0-sw123.yaml")
    first_evidence = SimulationEvidence.model_validate(raw)
    db = _Session()
    first_row = upsert_simulation_evidence(db, first_evidence, yaml_sha256="sha-first")
    exported_artifacts = list(first_row.artifacts)

    rerun_raw = dict(raw)
    rerun_raw["artifacts"] = []
    rerun_raw["kpi"] = {**raw["kpi"], "total_power_mw": 999.0}
    rerun_evidence = SimulationEvidence.model_validate(rerun_raw)

    rerun_row = upsert_simulation_evidence(db, rerun_evidence, yaml_sha256="sha-rerun")

    assert rerun_row is first_row
    assert rerun_row.kpi["total_power_mw"] == 999.0
    assert rerun_row.artifacts == exported_artifacts


def test_upsert_simulation_evidence_persists_project_ref():
    """The API persist path must keep project_ref like the ETL mapper does;
    losing it silently breaks every ?project_ref= filter and comparison."""
    raw = _load("sim-camera-recording-UHD60-EVT0-sw123.yaml")
    evidence = SimulationEvidence.model_validate(raw)
    assert evidence.project_ref  # fixture must carry one for this test to mean anything

    db = _Session()
    row = upsert_simulation_evidence(db, evidence, yaml_sha256="sha-x")

    assert row.project_ref == str(evidence.project_ref)
    assert db.rows[evidence.id].project_ref == str(evidence.project_ref)
