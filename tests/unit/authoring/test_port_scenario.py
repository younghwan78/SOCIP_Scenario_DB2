"""R-8 port: an E2600 scenario source copied into an ejected root project (a tmp copy of the authoring tree)."""

import shutil
from pathlib import Path

import pytest

from scenario_db.authoring import yamlio
from scenario_db.authoring.cli import main
from scenario_db.authoring.errors import AuthoringError
from scenario_db.authoring.port import RECORD, port_scenario, port_status

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture()
def root(tmp_path):
    """A private copy of the authoring tree: the public sm-s957b sources are never written."""
    shutil.copytree(REPO / "authoring", tmp_path / "authoring")
    return tmp_path / "authoring"


def test_a_ported_capture_runs_on_the_target_catalog(root):
    res = port_scenario(root, "uc-cam-capture-e2600", src="sm-s947b", dst="sm-s957b", commit="abc1234")
    assert res["scenario"] == "uc-cam-capture-e2700" and res["problems"] == [] and res["rewritten_by_dump"] == []
    assert res["smoke"]["ok"] == res["smoke"]["variants"] == 29 and res["smoke"]["errors"] == {}
    ddir = root / "projects" / "sm-s957b" / "scenarios" / "uc-cam-capture-e2700"
    assert {"scenario.yaml", "variants.yaml", "knobs.yaml", "jobs.measured.yaml", RECORD} <= {p.name for p in ddir.iterdir()}
    text = "".join(p.read_text(encoding="utf-8") for p in ddir.glob("*.yaml") if p.name != RECORD)
    for token in ("s5e9965", "e2600", "sm-s947b", "exynos2600"):
        assert token not in text, token
    assert "# R-6 KPI targets" in (ddir / "scenario.yaml").read_text(encoding="utf-8")   # comments survive
    record = yamlio.load(ddir / RECORD)
    assert record["source_scenario"] == "uc-cam-capture-e2600" and record["commit"] == "abc1234"
    assert set(record["files"]) == {p.name for p in (root / "projects/sm-s947b/scenarios/uc-cam-capture-e2600").glob("*.yaml")}


def test_the_smoke_run_names_what_the_target_catalog_lacks(root):
    res = port_scenario(root, "uc-game-play-e2600", src="sm-s947b", dst="sm-s957b")
    assert res["problems"] == [] and res["smoke"]["ok"] == 0
    [(message, variants)] = res["smoke"]["errors"].items()
    assert "gpu: domain load util-vf-v1 needs coeff_uw_per_mhz_v2" in message and len(variants) == 8


def test_port_status_sees_source_changes(root):
    port_scenario(root, "uc-aud-mp3-playback-e2600", src="sm-s947b", dst="sm-s957b", smoke=False)
    clean = port_status(root, "sm-s957b", "uc-aud-mp3-playback-e2700")
    assert clean["changed"] == clean["added"] == clean["removed"] == [] and not clean["source_missing"]
    src = root / "projects/sm-s947b/scenarios/uc-aud-mp3-playback-e2600"
    (src / "variants.yaml").write_text((src / "variants.yaml").read_text(encoding="utf-8") + "\n# edited\n",
                                       encoding="utf-8")
    (src / "extra.yaml").write_text("a: 1\n", encoding="utf-8")
    moved = port_status(root, "sm-s957b", "uc-aud-mp3-playback-e2700")
    assert moved["changed"] == ["variants.yaml"] and moved["added"] == ["extra.yaml"]


def test_port_refusals(root):
    port_scenario(root, "uc-aud-mp3-playback-e2600", src="sm-s947b", dst="sm-s957b", smoke=False)
    with pytest.raises(AuthoringError, match="already exists"):
        port_scenario(root, "uc-aud-mp3-playback-e2600", src="sm-s947b", dst="sm-s957b", smoke=False)
    again = port_scenario(root, "uc-aud-mp3-playback-e2600", src="sm-s947b", dst="sm-s957b", smoke=False, replace=True)
    assert again["scenario"] == "uc-aud-mp3-playback-e2700"
    suffixed = port_scenario(root, "uc-aud-mp3-playback-e2600", src="sm-s947b", dst="sm-s957b", suffix="-v2",
                             smoke=False)
    assert suffixed["scenario"] == "uc-aud-mp3-playback-e2700-v2"
    with pytest.raises(AuthoringError, match="no scenario source"):
        port_scenario(root, "uc-nope", src="sm-s947b", dst="sm-s957b")
    with pytest.raises(AuthoringError, match="no ejected-from.yaml"):
        port_scenario(root, "uc-cam-recording-e2700", src="sm-s957b", dst="sm-s947b")


def test_the_cli_reports_and_exits_on_smoke_errors(root, capsys):
    assert main(["--root", str(root), "port-scenario", "uc-aud-streaming-e2600", "--from", "sm-s947b",
                 "--to", "sm-s957b", "--commit", "x"]) == 0
    assert '"scenario": "uc-aud-streaming-e2700"' in capsys.readouterr().out
    assert main(["--root", str(root), "port-scenario", "uc-game-play-e2600", "--from", "sm-s947b",
                 "--to", "sm-s957b", "--commit", "x"]) == 1
    assert main(["--root", str(root), "port-status", "sm-s957b", "uc-aud-streaming-e2700"]) == 0
