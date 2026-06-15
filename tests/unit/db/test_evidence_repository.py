from __future__ import annotations

from pathlib import Path

import yaml

from scenario_db.db.repositories.evidence import upsert_simulation_evidence
from scenario_db.models.evidence.simulation import SimulationEvidence

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "evidence"


class _Query:
    def filter_by(self, **kwargs):
        return self

    def one_or_none(self):
        return None


class _Session:
    def __init__(self):
        self.rows = {}

    def query(self, model):
        return _Query()

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
