from __future__ import annotations

from pathlib import Path

from scenario_db.etl.retire import load_spec

REPO = Path(__file__).resolve().parents[2]


def test_repository_retire_spec_only_narrows_exynos2700():
    spec = load_spec(REPO / "authoring" / "retired.yaml")
    # Exynos2600 is the complete reference: no project / SoC / IP / scenario of it is retired
    assert not spec["projects"] and not spec["socs"] and not spec["ips"]
    assert spec["scenarios"] and all(s.endswith("-e2700") for s in spec["scenarios"])
    assert "uc-cam-recording-e2700" not in spec["scenarios"]
    assert ("uc-cam-recording-e2700", "cam-rec-r1-fhd30-sdr") in spec["variants"]
    assert ("uc-cam-recording-e2700", "cam-rec-r1-uhd30-vdis") not in spec["variants"]
    # 2600 side: only rows the withdrawn 2600 reduction put under camera recording (APV merge, Pro video)
    e2600 = {(sc, v) for sc, v in spec["variants"] if sc.endswith("-e2600")}
    assert e2600 and all(sc == "uc-cam-recording-e2600" for sc, _ in e2600)
    assert all(v.startswith("cam-rec-apv-") or v.endswith("-pro") for _, v in e2600)


def test_retire_spec_never_touches_rows_the_fixtures_load():
    from scenario_db.authoring.tree import compile_project

    spec = load_spec(REPO / "authoring" / "retired.yaml")
    loaded: set[tuple[str, str]] = set()
    scenarios: set[str] = set()
    for key in ("sm-s947b", "sm-s957b"):
        for d in compile_project(REPO / "authoring", key)["documents"]:
            if isinstance(d.data, dict) and d.data.get("kind") == "scenario.usecase":
                scenarios.add(d.data["id"])
                loaded |= {(d.data["id"], v["id"]) for v in d.data.get("variants") or []}
    assert not spec["scenarios"] & scenarios
    assert not spec["variants"] & loaded


def test_load_spec_accumulates_entries(tmp_path: Path):
    p = tmp_path / "r.yaml"
    p.write_text("retire:\n- projects: [a]\n  variants: {s: [v1]}\n- scenarios: [s2]\n  variants: {s: [v2]}\n", encoding="utf-8")
    spec = load_spec(p)
    assert spec["projects"] == {"a"} and spec["scenarios"] == {"s2"}
    assert spec["variants"] == {("s", "v1"), ("s", "v2")}
