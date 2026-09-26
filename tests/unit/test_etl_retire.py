from __future__ import annotations

from pathlib import Path

from scenario_db.etl.retire import load_spec

REPO = Path(__file__).resolve().parents[2]


def test_repository_retire_spec_covers_scope_reduction():
    spec = load_spec(REPO / "authoring" / "retired.yaml")
    assert "proj-sm-s957b" in spec["projects"] and "soc-exynos2700" in spec["socs"]
    assert "ip-*-s5e9975" in spec["ips"]
    assert "uc-vid-youtube-e2600" in spec["scenarios"]
    # APV is merged (renamed), not retired
    assert "uc-cam-recording-apv-e2600" not in spec["scenarios"]
    assert ("uc-cam-recording-e2600", "cam-rec-r1-fhd30-sdr") in spec["variants"]
    assert ("uc-cam-recording-e2600", "cam-rec-r1-uhd30-vdis") not in spec["variants"]


def test_load_spec_accumulates_entries(tmp_path: Path):
    p = tmp_path / "r.yaml"
    p.write_text("retire:\n- projects: [a]\n  variants: {s: [v1]}\n- scenarios: [s2]\n  variants: {s: [v2]}\n", encoding="utf-8")
    spec = load_spec(p)
    assert spec["projects"] == {"a"} and spec["scenarios"] == {"s2"}
    assert spec["variants"] == {("s", "v1"), ("s", "v2")}
