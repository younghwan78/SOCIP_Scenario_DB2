"""db_Exynos2700_SM-S957B: every variant has a prediction with a timeline (Pipeline timing diagram)."""
from __future__ import annotations

from pathlib import Path

import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from generate_simulation_evidence import expected_params_hash  # noqa: E402

from scenario_db.api.services.calibration import is_synthetic  # noqa: E402

DB = Path(__file__).resolve().parents[2] / "db_Exynos2700_SM-S957B"


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_every_variant_has_simulation_evidence_with_timeline():
    scenario = _read(DB / "02_definition" / "uc-cam-recording-e2700.yaml")
    variants = {v["id"] for v in scenario["variants"]}
    sims = [_read(p) for p in sorted((DB / "03_evidence").glob("sim-*.yaml"))]
    assert {s["variant_ref"] for s in sims} == variants
    for s in sims:
        assert s["kind"] == "evidence.simulation"
        assert (s["project_ref"], s["scenario_ref"]) == ("proj-sm-s957b", "uc-cam-recording-e2700")
        assert s["execution_context"]["sw_baseline_ref"] == "sw-vendor-v1.2.3-s5e9975"
        assert len({e["frame_index"] for e in s["timeline_events"]}) == 8, s["id"]
        assert all(n["ip_ref"].endswith("s5e9975") for n in s.get("ip_breakdown") or [] if n.get("ip_ref"))


def test_simulation_evidence_is_not_stale():
    """Authoring changed (HW patch, SW timing, overlay) -> rerun scripts/generate_simulation_evidence.py."""
    for path in sorted((DB / "03_evidence").glob("sim-*.yaml")):
        ev = _read(path)
        assert ev["params_hash"] == expected_params_hash(DB, ev["scenario_ref"], ev), (
            f"{path.name} is stale: python scripts/generate_simulation_evidence.py {DB.name} {ev['scenario_ref']}")


def test_dummy_measurements_are_flagged_synthetic():
    """UI / calibration must not count DUMMY inputs as real measurements."""
    for path in sorted((DB / "03_evidence").glob("meas-*.yaml")):
        assert is_synthetic(_read(path)["provenance"]), path.name
