from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scenario_db.models.evidence.measurement import MeasurementEvidence
from scenario_db.models.evidence.metrics import load_default_metric_catalog
from scenario_db.models.evidence.simulation import SimulationEvidence

FIXTURES = Path(__file__).parent / "fixtures" / "evidence"


def _load(name: str) -> dict:
    return yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))


def test_default_metric_catalog_has_canonical_camera_metrics():
    catalog = load_default_metric_catalog()

    assert catalog.metrics["power.rail"].canonical_unit == "mW"
    assert catalog.metrics["bandwidth.total"].kpi_key == "total_bw_mbs"
    assert catalog.metrics["sw.start_jitter"].allowed_scopes == {"task", "thread"}


def test_measurement_accepts_catalog_validated_metric_observations():
    raw = _load("meas-camera-recording-UHD60-EVT0-sw123.yaml")
    raw["metric_observations"] = [
        {
            "metric_id": "sw.start_jitter",
            "scope": {"kind": "task", "ref": "eis_warp"},
            "unit": "us",
            "stats": {"mean": 84.0, "p95": 210.0, "max": 620.0, "n": 5400},
        }
    ]

    evidence = MeasurementEvidence.model_validate(raw)

    assert evidence.metric_observations[0].scope.ref == "eis_warp"
    assert evidence.metric_observations[0].stats.p95 == 210.0


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"metric_id": "custom.unknown"}, "unknown metric_id"),
        ({"scope": {"kind": "rail", "ref": "eis_warp"}}, "does not allow scope"),
        ({"unit": "ms"}, "requires unit 'us'"),
    ],
)
def test_measurement_rejects_unknown_scope_or_unit(patch: dict, message: str):
    raw = _load("meas-camera-recording-UHD60-EVT0-sw123.yaml")
    observation = {
        "metric_id": "sw.start_jitter",
        "scope": {"kind": "task", "ref": "eis_warp"},
        "unit": "us",
        "value": 84.0,
    }
    observation.update(patch)
    raw["metric_observations"] = [observation]

    with pytest.raises(ValidationError, match=message):
        MeasurementEvidence.model_validate(raw)


def test_measurement_rejects_duplicate_metric_identity():
    raw = _load("meas-camera-recording-UHD60-EVT0-sw123.yaml")
    observation = {
        "metric_id": "power.rail",
        "scope": {"kind": "rail", "ref": "VDD_CAM"},
        "unit": "mW",
        "value": 640.0,
    }
    raw["metric_observations"] = [observation, copy.deepcopy(observation)]

    with pytest.raises(ValidationError, match="duplicate metric observation"):
        MeasurementEvidence.model_validate(raw)


def test_simulation_accepts_metric_observations():
    raw = _load("sim-camera-recording-UHD60-EVT0-sw123.yaml")
    raw["metric_observations"] = [
        {
            "metric_id": "bandwidth.read",
            "scope": {"kind": "dma_port", "ref": "isp0:RDMA0"},
            "unit": "MB/s",
            "value": 1420.0,
        }
    ]

    evidence = SimulationEvidence.model_validate(raw)

    assert evidence.metric_observations[0].value == 1420.0
