from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scenario_db.meas_import.fullstack import handoff_flows
from scenario_db.models.evidence.handoff import HandoffDoc
from scenario_db.models.evidence.measurement import MeasurementEvidence

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "docs" / "contracts" / "data" / "sdb-handoff-1.schema.json"
FIXTURES = sorted((ROOT / "db_Exynos2600_SM-S947B" / "03_evidence").glob("meas-synth-fullstack-*.yaml"))


def _doc(**over):
    doc = {
        "format": "sdb.handoff/1",
        "participants": [
            {"id": "hal.cam", "layer": "hal", "name": "camera.provider"},
            {"id": "hw.isp", "layer": "hw", "name": "ISP"},
            {"id": "hw.vps", "layer": "hw", "name": "VPS"},
        ],
        "cadences": [
            {"id": "frame", "name": "Sensor frame", "kind": "frame", "period_ms": 33.333},
            {"id": "od", "name": "VPS OD", "kind": "divided", "of": "frame", "every": 5},
            {"id": "touch", "name": "Touch", "kind": "event"},
        ],
        "flows": [{"id": "f", "name": "frame", "cadence": "frame", "steps": [
            {"to": "hal.cam", "call": "request", "task": "hal.request", "frame_offset": -4, "t_ms": 0, "dur_ms": 2.3},
            {"note": "SOF n", "over": ["hw.isp"]},
            {"from": "hal.cam", "to": "hw.isp", "call": "kick", "handoff": "kick", "t_ms": 3, "dur_ms": 10},
            {"from": "hw.isp", "to": "hw.vps", "call": "OD", "cadence": "od", "every": 5, "branch": "od"},
        ]}],
    }
    doc.update(over)
    return doc


def test_valid_document_round_trips_with_from_alias():
    doc = HandoffDoc.model_validate(_doc())
    dumped = doc.model_dump(by_alias=True, exclude_none=True, exclude_defaults=True)
    assert dumped["flows"][0]["steps"][2]["from"] == "hal.cam"
    assert "handoff" not in dumped["flows"][0]["steps"][0]          # default data is not stored
    assert HandoffDoc.model_validate(dumped) == doc


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["flows"][0]["steps"].append({"from": "hal.cam", "to": "hw.nope"}), "unknown participant hw.nope"),
    (lambda d: d["flows"][0]["steps"].append({"to": "hw.isp", "cadence": "vsync"}), "unknown cadence vsync"),
    (lambda d: d["flows"][0].update(cadence="vsync"), "flow f: unknown cadence"),
    (lambda d: d["participants"].append({"id": "hw.isp", "layer": "hw", "name": "x"}), "duplicate participant id"),
    (lambda d: d["cadences"].append({"id": "x", "name": "x", "kind": "period"}), "needs period_ms"),
    (lambda d: d["cadences"].append({"id": "x", "name": "x", "kind": "divided", "of": "nope", "every": 2}), "unknown base cadence"),
    (lambda d: d["participants"].append({"id": "x", "layer": "driver", "name": "x"}), "layer"),
    (lambda d: d["flows"][0]["steps"].append({"note": "n", "over": ["hw.isp"], "to": "hw.isp"}), "note step takes note"),
    (lambda d: d["flows"][0]["steps"].append({"from": "hw.isp", "handoff": "kick"}), "call step needs to"),
    (lambda d: d["flows"][0]["steps"].append({"to": "hw.isp", "html": "<script>"}), "html"),
])
def test_invalid_documents_are_rejected(mutate, message):
    doc = _doc()
    mutate(doc)
    with pytest.raises(ValidationError, match=message):
        HandoffDoc.model_validate(doc)


def test_import_reports_steps_the_trace_does_not_contain():
    raw = _doc()
    raw["flows"][0]["steps"][0]["slice"] = "hal.request#f4"
    raw["flows"][0]["steps"][2]["task"] = "isp.kick"
    events = [{"task_id": "hal.request#f4", "logical_task_id": "hal.request"}]
    stored, report = handoff_flows(raw, events)
    assert stored["format"] == "sdb.handoff/1"
    assert report == {"flows": 1, "steps": 3, "cadences": 3, "unknown_tasks": ["isp.kick"], "unknown_slices": []}


def test_published_json_schema_matches_the_model():
    # the in-house hand-off tool validates against this file; regenerate it with
    # json.dumps(HandoffDoc.model_json_schema(by_alias=True), indent=2, ensure_ascii=False) + "\n"
    expected = json.dumps(HandoffDoc.model_json_schema(by_alias=True), indent=2, ensure_ascii=False) + "\n"
    assert SCHEMA.read_text(encoding="utf-8") == expected, "regenerate docs/contracts/data/sdb-handoff-1.schema.json"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_e2600_fixture_flows_point_at_real_slices(path):
    ev = MeasurementEvidence.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert ev.handoff_flows is not None
    slices = {e["task_id"] for e in ev.timeline_events}
    steps = [s for f in ev.handoff_flows.flows for s in f.steps if s.note is None]
    assert steps and all(s.slice in slices for s in steps)
    # every rate used by a step is declared, and at least one step leaves its flow's cadence or a flow is not frame-locked
    kinds = {c.id: c.kind for c in ev.handoff_flows.cadences}
    assert any(s.cadence for s in steps) or any(kinds[f.cadence] != "frame" for f in ev.handoff_flows.flows)


def test_e2600_fixtures_cover_four_scenarios():
    assert {yaml.safe_load(p.read_text(encoding="utf-8"))["scenario_ref"] for p in FIXTURES} == {
        "uc-cam-recording-e2600", "uc-vid-youtube-e2600", "uc-vid-playback-local-e2600", "uc-game-play-e2600"}
