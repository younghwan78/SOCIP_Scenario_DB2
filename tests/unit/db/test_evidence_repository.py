from __future__ import annotations

from pathlib import Path

import yaml

from scenario_db.db.repositories.evidence import upsert_simulation_evidence
from scenario_db.models.evidence.simulation import SimulationEvidence

FIXTURES = Path(__file__).parent.parent / "fixtures" / "evidence"


class _Query:
    def __init__(self, rows: dict):
        self.rows = rows
        self._id = None

    def filter_by(self, **kwargs):
        self._id = kwargs.get("id")
        return self

    def one_or_none(self):
        return self.rows.get(self._id)


class _Session:
    def __init__(self):
        self.rows: dict = {}

    def query(self, model):
        return _Query(self.rows)

    def add(self, row):
        self.rows[row.id] = row


def test_upsert_simulation_evidence_persists_project_ref():
    """The API persist path must keep project_ref like the ETL mapper does;
    losing it silently breaks every ?project_ref= filter and comparison."""
    raw = yaml.safe_load(
        (FIXTURES / "sim-camera-recording-UHD60-EVT0-sw123.yaml").read_text(encoding="utf-8")
    )
    evidence = SimulationEvidence.model_validate(raw)
    assert evidence.project_ref  # fixture must carry one for this test to mean anything

    db = _Session()
    row = upsert_simulation_evidence(db, evidence, yaml_sha256="sha-x")

    assert row.project_ref == str(evidence.project_ref)
    assert db.rows[evidence.id].project_ref == str(evidence.project_ref)
