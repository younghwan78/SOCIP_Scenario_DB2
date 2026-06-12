from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from scenario_db.etl.mappers.evidence import upsert_measurement, upsert_simulation

FIXTURES = Path(__file__).parent / "fixtures" / "evidence"


class _Session:
    def __init__(self):
        self.rows = {}

    def get(self, model, key):
        return self.rows.get(key)

    def add(self, row):
        self.rows[row.id] = row


def _load(name: str) -> dict:
    return yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))


def test_upsert_measurement_persists_detail_fields():
    db = _Session()
    raw = _load("meas-camera-recording-UHD60-EVT0-sw123.yaml")

    upsert_measurement(raw, "sha-meas-1", db)

    row = db.rows[raw["id"]]
    assert row.kind == "evidence.measurement"
    assert row.project_ref == "proj-A-exynos2500"
    assert isinstance(row.measured_at, datetime)
    assert row.measured_at.isoformat() == "2026-04-19T14:30:00+09:00"
    assert row.derived_from is None  # 빈 lineage는 NULL로 저장
    assert row.execution_context["method"] == "measurement"

    clusters = {c["cluster"] for c in row.cpu_breakdown}
    assert clusters == {"BIG", "MID", "LIT"}
    big = next(c for c in row.cpu_breakdown if c["cluster"] == "BIG")
    assert big["power_mw"]["mean"] == 820.0
    assert big["freq_residency"][1]["ratio"] == 0.52

    tasks = {t["task"] for t in row.sw_task_timing}
    assert "eis_warp" in tasks

    assert row.vdd_power["VDD_NPU"]["p95_mw"] == 350.0
    assert row.timeline_events[0]["type"] == "frame_drop"
    assert row.artifacts[0]["type"] == "perfetto_trace"
    assert row.provenance["device_id"] == "EVT0-S24-SN-1234"


def test_upsert_measurement_skips_identical_sha():
    db = _Session()
    raw = _load("meas-camera-recording-UHD60-EVT0-sw123.yaml")

    upsert_measurement(raw, "sha-meas-1", db)
    row = db.rows[raw["id"]]
    row.kpi = {"sentinel": 1}

    upsert_measurement(raw, "sha-meas-1", db)
    assert db.rows[raw["id"]].kpi == {"sentinel": 1}


def test_upsert_simulation_persists_lineage_fields():
    db = _Session()
    raw = _load("sim-camera-recording-UHD60-EVT0-sw123.yaml")
    raw["project_ref"] = "proj-A-exynos2500"
    raw["derived_from"] = ["meas-uc-camera-recording-UHD60-HDR10-H265-EVT0-sw123-20260419"]
    raw["execution_context"]["method"] = "projection"

    upsert_simulation(raw, "sha-sim-1", db)

    row = db.rows[raw["id"]]
    assert row.project_ref == "proj-A-exynos2500"
    assert row.derived_from == ["meas-uc-camera-recording-UHD60-HDR10-H265-EVT0-sw123-20260419"]
    assert row.execution_context["method"] == "projection"
