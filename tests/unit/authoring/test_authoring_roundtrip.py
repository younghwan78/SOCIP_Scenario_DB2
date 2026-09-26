from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scenario_db.authoring import yamlio
from scenario_db.authoring.cli import check_against, write_worksheet
from scenario_db.authoring.patch import deep_merge, make_patch
from scenario_db.authoring.scenario import AuthoringError, expand_variants
from scenario_db.authoring.tree import compile_project
from scenario_db.authoring.validate import validate_documents

REPO = Path(__file__).resolve().parents[3]
AUTHORING = REPO / "authoring"
FIXTURE = REPO / "db_fixtures_Exynos2600_S26Plus"
EXAMPLE_2800 = AUTHORING / "examples" / "exynos2800-pipeline-change"


def _docs(report: dict) -> dict[str, dict]:
    return {d.data["id"]: d.data for d in report["documents"] if isinstance(d.data, dict) and "id" in d.data}


def _variant(doc: dict, vid: str) -> dict:
    return next(v for v in doc["variants"] if v["id"] == vid)


@pytest.fixture()
def scratch_root(tmp_path: Path) -> Path:
    root = tmp_path / "authoring"
    shutil.copytree(AUTHORING, root, ignore=shutil.ignore_patterns("examples"))
    return root


# --- patch semantics --------------------------------------------------------

def test_make_patch_roundtrips_with_unset_and_type_changes():
    base = {"a": 1, "b": {"c": [1, 2], "d": "x"}, "gone": True, "f": 30}
    target = {"a": 1, "b": {"c": [1, 2, 3]}, "new": {"k": 1}, "f": 30.0}
    patch = make_patch(base, target)
    assert patch["$unset"] == ["gone"]
    assert deep_merge(base, patch) == target
    assert type(deep_merge(base, patch)["f"]) is float


def test_expand_variants_rejects_cycles_and_unknown_parents():
    with pytest.raises(AuthoringError, match="cycle"):
        expand_variants([{"id": "a", "extends": "b"}, {"id": "b", "extends": "a"}])
    with pytest.raises(AuthoringError, match="unknown variant"):
        expand_variants([{"id": "a", "extends": "zz"}])


# --- Exynos2600: authoring is lossless vs. the canonical fixture ------------

def test_exynos2600_authoring_compiles_to_the_canonical_fixture():
    assert check_against(AUTHORING, "sm-s947b", FIXTURE) == []


def test_exynos2600_compiled_documents_validate():
    report = compile_project(AUTHORING, "sm-s947b")
    result = validate_documents(report["documents"])
    assert result["errors"] == []
    assert report["impact"] == {}


# --- Exynos2700: inherit + rename + measurement slots -----------------------

CHILD = "t2600x"
CHILD_UC = "uc-cam-recording-e2600x"


def _write_child(root: Path, overlay: dict | None = None) -> None:
    """Scratch derived project on the same platform (inheritance / overlay / knob tests)."""
    jdir = root / "projects" / CHILD
    yamlio.dump(jdir / "project.yaml", {
        "kind": "authoring.project", "key": CHILD, "platform": "exynos2600", "extends": "sm-s947b",
        "rename": [{"from": "proj-sm-s947b", "to": "proj-t2600x"}, {"from": "-e2600", "to": "-e2600x"}],
        "document_patch": {"metadata": {"board_type": "T2600X"}},
    })
    yamlio.dump(jdir / "scenarios" / "uc-cam-recording-e2600" / "overlay.yaml", overlay or {"variants": {"add": [
        {"id": "cam-rec-r1-uhd30-vdis-bcrop", "extends": "cam-rec-r1-uhd30-vdis",
         "design_conditions": {"crop_strategy": "byrp_bcrop"}},
        {"id": "cam-rec-r1-uhd30-vdis-bcrop-l0skip", "extends": "cam-rec-r1-uhd30-vdis-bcrop",
         "design_conditions": {"pyramid_l0": "skip"}},
    ]}})


@pytest.fixture()
def child_root(scratch_root: Path) -> Path:
    _write_child(scratch_root)
    return scratch_root


def _child_recording(root: Path) -> dict:
    return _docs(compile_project(root, CHILD))[CHILD_UC]


def test_exynos2600_scope_is_the_camera_recording_kpi_set():
    rec = _docs(compile_project(AUTHORING, "sm-s947b"))["uc-cam-recording-e2600"]
    ids = {v["id"] for v in rec["variants"]}
    assert len(ids) == 18
    assert {"cam-rec-apv-uhd120-422-sdr", "cam-rec-r1-uhd60-pro", "cam-rec-pip-uhd30"} <= ids
    apv = _variant(rec, "cam-rec-apv-uhd30-422-sdr")
    assert "mfc_enc" in apv["routing_switch"]["disabled_nodes"]
    assert any(n["id"] == "apv_enc" for n in apv["topology_patch"]["add_nodes"])
    assert "pro_scope" in _variant(rec, "cam-rec-r1-uhd30-pro")["node_configs"]


def test_derived_project_inherits_with_renamed_ids(child_root: Path):
    report = compile_project(child_root, CHILD)
    docs = _docs(report)
    assert validate_documents(report["documents"])["errors"] == []
    assert docs["proj-t2600x"]["metadata"]["board_type"] == "T2600X"
    rec = docs[CHILD_UC]
    assert rec["project_ref"] == "proj-t2600x"
    assert rec["metadata"]["canonical_usecase"] == "uc-cam-recording"
    assert len(rec["variants"]) == 18 + 2
    assert "simcfg-proj-t2600x-v1" in docs


def test_sw_timing_measurement_overrides_only_the_selected_scope(child_root: Path):
    target = child_root / f"projects/{CHILD}/scenarios/uc-cam-recording-e2600/sw_timing.measured.yaml"
    yamlio.dump(target, {"entries": [{
        "task": "post_crta", "group": "post_crta-a", "when": {"resolution": "UHD"},
        "timing": {"mean_ms": 0.42, "value_source": "measured", "source_note": "perfetto test"},
    }]})
    rec = _child_recording(child_root)
    uhd = _variant(rec, "cam-rec-r1-uhd30-vdis")["node_configs"]["post_crta"]["sw_timing"]
    fhd = _variant(rec, "cam-rec-r1-fhd30-vdis")["node_configs"]["post_crta"]["sw_timing"]
    assert uhd["mean_ms"] == 0.42 and uhd["value_source"] == "measured" and uhd["max_ms"] == 0.5
    assert fhd["mean_ms"] == 0.3 and fhd["value_source"] == "assumed"


def test_worksheet_creates_slots_once(child_root: Path):
    written = write_worksheet(child_root, CHILD)
    assert [p.parent.name for p in written] == ["uc-cam-recording-e2600"]
    assert write_worksheet(child_root, CHILD) == []
    assert compile_project(child_root, CHILD)["measurements"][CHILD_UC]["pending"] > 0


def test_derived_anchor_drives_bound_node_sizes(scratch_root: Path):
    """EIS-margin style rule: eis_in = record_out * 1.25 (16-aligned) feeding MSNR."""
    _write_child(scratch_root, {"sizes": {
        "derived": {"eis_in": {"from": "record_out", "scale": 1.25, "align": 16}},
        "bindings": {"msnr": "eis_in"},
    }})
    rec = _child_recording(scratch_root)
    v = _variant(rec, "cam-rec-r1-fhd30-vdis")
    assert v["size_overrides"]["eis_in"] == "2400x1360"
    assert (v["node_configs"]["msnr"]["sim"]["width"], v["node_configs"]["msnr"]["sim"]["height"]) == (2400, 1360)
    assert _variant(rec, "cam-rec-r1-uhd30-vdis")["size_overrides"]["eis_in"] == "4800x2704"


# --- Exynos2800-style pipeline change ---------------------------------------

def _with_example(root: Path) -> None:
    for sub in ("platforms", "projects"):
        shutil.copytree(EXAMPLE_2800 / sub, root / sub, dirs_exist_ok=True)


def test_pipeline_change_example(scratch_root: Path):
    _with_example(scratch_root)
    report = compile_project(scratch_root, "e2800-concept")
    assert validate_documents(report["documents"])["errors"] == []
    rec = _docs(report)["uc-cam-recording-e2800c"]
    nodes = {n["id"]: n for n in rec["pipeline"]["nodes"]}
    assert "msnr" not in nodes
    assert nodes["mtnr"]["ip_ref"] == "ip-nr-v2-exynos2800c"
    assert all(n["ip_ref"].endswith("exynos2800c") for n in rec["pipeline"]["nodes"])
    assert any(e["from"] == "mtnr" and e["to"] == "yuvp" for e in rec["pipeline"]["edges"])
    impact = report["impact"]["uc-cam-recording-e2800c"]
    assert impact and all("msnr" in line for line in impact)
    assert all("msnr" not in (v.get("node_configs") or {}) for v in rec["variants"])


def test_pipeline_change_without_prune_fails_with_impact_list(scratch_root: Path):
    _with_example(scratch_root)
    overlay_path = scratch_root / "projects/e2800-concept/scenarios/uc-cam-recording-e2600/overlay.yaml"
    overlay = yamlio.load(overlay_path)
    overlay["prune_missing_nodes"] = False
    yamlio.dump(overlay_path, overlay)
    with pytest.raises(AuthoringError, match="node_configs.msnr"):
        compile_project(scratch_root, "e2800-concept")


# --- architecture knobs (crop strategy / EIS margin / pyramid L0) -----------

def test_byrp_bcrop_shrinks_the_chain_to_the_eis_window(child_root: Path):
    rec = _child_recording(child_root)
    base = _variant(rec, "cam-rec-r1-uhd30-vdis")
    bcrop = _variant(rec, "cam-rec-r1-uhd30-vdis-bcrop")
    assert "bcrop_out" not in base["size_overrides"]
    assert base["node_configs"]["mtnr"]["sim"]["width"] == 4080
    so = bcrop["size_overrides"]
    assert so["bcrop_out"] == "3760x2114" == so["mlsc_out"] == so["pyramid_l0"]
    assert so["pyramid_l1"] == "1880x1057" and so["pyramid_l4"] == "235x133"
    sims = {n: (bcrop["node_configs"][n]["sim"]["width"], bcrop["node_configs"][n]["sim"]["height"])
            for n in ("byrp", "rgbp", "mtnr", "mcsc")}
    assert sims == {"byrp": (4080, 2296), "rgbp": (3760, 2114), "mtnr": (3760, 2114), "mcsc": (3760, 2114)}
    assert bcrop["node_configs"]["byrp"]["operations"]["crop"] is True
    assert bcrop["node_configs"]["mcsc"]["operations"] == {"crop": False, "scale": True}
    conds = bcrop["design_conditions"]
    assert (conds["crop_strategy"], conds["eis_margin_pct"], conds["sensor_margin_pct"]) == ("byrp_bcrop", 15, 25)
    tasks = lambda v: sorted(k for k, c in v["node_configs"].items() if "sw_timing" in c)  # noqa: E731
    assert tasks(bcrop) == tasks(base)


def test_pyramid_l0_skip_removes_only_the_l0_level(child_root: Path):
    rec = _child_recording(child_root)
    v = _variant(rec, "cam-rec-r1-uhd30-vdis-bcrop-l0skip")
    assert {"from": "mlsc", "to": "mtnr", "buffer": "PYRAMID_L0"} in v["topology_patch"]["remove_edges"]
    assert {"from": "mlsc", "to": "mtnr", "buffer": "PYRAMID_L0"} not in (
        _variant(rec, "cam-rec-r1-uhd30-vdis-bcrop").get("topology_patch", {}).get("remove_edges") or [])


def test_bcrop_without_eis_keeps_full_sensor_fov(scratch_root: Path):
    _write_child(scratch_root, {"variants": {"add": [
        {"id": "psm-bcrop", "extends": "cam-rec-r1-uhd60-psm", "design_conditions": {"crop_strategy": "byrp_bcrop"}}]}})
    v = _variant(_child_recording(scratch_root), "psm-bcrop")
    assert "eis" in v["routing_switch"]["disabled_nodes"]
    assert v["size_overrides"]["bcrop_out"] == v["size_overrides"]["sensor_full"]
    assert v["design_conditions"]["eis_margin_pct"] == 25


# --- bidirectional transition -----------------------------------------------

def test_sync_to_fixture_is_idempotent(tmp_path: Path):
    from scenario_db.authoring.cli import sync_to_fixture

    out = tmp_path / "fixture"
    first = sync_to_fixture(AUTHORING, "sm-s947b", out)
    assert first["added"] and not first["updated"]
    second = sync_to_fixture(AUTHORING, "sm-s947b", out)
    assert not second["added"] and not second["updated"]
    assert sync_to_fixture(AUTHORING, "sm-s947b", FIXTURE, dry_run=True)["updated"] == []


def test_fixture_with_knob_variants_decompiles_and_recompiles(child_root: Path, tmp_path: Path):
    from scenario_db.authoring.cli import sync_to_fixture
    from scenario_db.authoring.tree import decompile_fixture

    out = tmp_path / "fixture"
    sync_to_fixture(child_root, CHILD, out)
    knobs_src = child_root / "projects/sm-s947b/scenarios/uc-cam-recording-e2600/knobs.yaml"
    knobs_dst = child_root / f"projects/rt/scenarios/{CHILD_UC}/knobs.yaml"
    knobs_dst.parent.mkdir(parents=True)
    shutil.copyfile(knobs_src, knobs_dst)
    decompile_fixture(out, child_root, "rt-platform", "rt")
    assert knobs_dst.exists()
    assert check_against(child_root, "rt", out) == []
