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

def test_e2700_inherits_all_scenarios_with_renamed_ids():
    report = compile_project(AUTHORING, "sm-s957b")
    docs = _docs(report)
    assert validate_documents(report["documents"])["errors"] == []
    assert "soc-exynos2700" in docs and "proj-sm-s957b" in docs
    assert not [i for i in docs if i.startswith("ip-") and "s5e9965" in i]
    assert "ip-mfc-s5e9975" in docs and "dvfs-exynos2700-sample-v0" in docs
    assert docs["proj-sm-s957b"]["metadata"]["soc_ref"] == "soc-exynos2700"
    assert docs["simcfg-proj-sm-s957b-v1"]["status"] == "draft"
    rec = docs["uc-cam-recording-e2700"]
    assert rec["project_ref"] == "proj-sm-s957b"
    assert rec["metadata"]["canonical_usecase"] == "uc-cam-recording"
    assert len(rec["variants"]) == 75 + 3   # inherited + exploration variants (overlay)
    assert all(n["ip_ref"].endswith("s5e9975") for n in rec["pipeline"]["nodes"])
    # shared sensor DT catalogs keep their ids (rename_exclude)
    assert "sensor-gng-m2s" in docs
    # pending measurement slots are reported, baseline kept
    assert report["measurements"]["uc-cam-recording-e2700"]["pending"] > 0


def test_sw_timing_measurement_overrides_only_the_selected_scope(scratch_root: Path):
    target = scratch_root / "projects/sm-s957b/scenarios/uc-cam-recording-e2600/sw_timing.measured.yaml"
    yamlio.dump(target, {"entries": [{
        "task": "post_crta", "group": "post_crta-a", "when": {"resolution": "UHD"},
        "timing": {"mean_ms": 0.42, "value_source": "measured", "source_note": "perfetto test"},
    }]})
    rec = _docs(compile_project(scratch_root, "sm-s957b"))["uc-cam-recording-e2700"]
    uhd = _variant(rec, "cam-rec-r1-uhd30-sdr")["node_configs"]["post_crta"]["sw_timing"]
    fhd = _variant(rec, "cam-rec-r1-fhd30-sdr")["node_configs"]["post_crta"]["sw_timing"]
    assert uhd["mean_ms"] == 0.42 and uhd["value_source"] == "measured" and uhd["max_ms"] == 0.5
    assert fhd["mean_ms"] == 0.3 and fhd["value_source"] == "assumed"


def test_worksheet_does_not_overwrite_existing_slots(scratch_root: Path):
    assert write_worksheet(scratch_root, "sm-s957b") == []


def test_derived_anchor_drives_bound_node_sizes(scratch_root: Path):
    """EIS-margin style rule: eis_in = record_out * 1.25 (16-aligned) feeding MSNR."""
    overlay = scratch_root / "projects/sm-s957b/scenarios/uc-cam-recording-e2600/overlay.yaml"
    yamlio.dump(overlay, {"sizes": {
        "derived": {"eis_in": {"from": "record_out", "scale": 1.25, "align": 16}},
        "bindings": {"msnr": "eis_in"},
    }})
    rec = _docs(compile_project(scratch_root, "sm-s957b"))["uc-cam-recording-e2700"]
    v = _variant(rec, "cam-rec-r1-fhd30-sdr")
    assert v["size_overrides"]["eis_in"] == "2400x1360"
    assert (v["node_configs"]["msnr"]["sim"]["width"], v["node_configs"]["msnr"]["sim"]["height"]) == (2400, 1360)
    u = _variant(rec, "cam-rec-r1-uhd30-sdr")
    assert u["size_overrides"]["eis_in"] == "4800x2704"


# --- Exynos2800-style pipeline change ---------------------------------------

def test_pipeline_change_example(scratch_root: Path):
    for sub in ("platforms", "projects"):
        shutil.copytree(EXAMPLE_2800 / sub, scratch_root / sub, dirs_exist_ok=True)
    report = compile_project(scratch_root, "e2800-concept")
    assert validate_documents(report["documents"])["errors"] == []
    rec = _docs(report)["uc-cam-recording-e2800c"]
    nodes = {n["id"]: n for n in rec["pipeline"]["nodes"]}
    assert "msnr" not in nodes
    assert nodes["mtnr"]["ip_ref"] == "ip-nr-v2-exynos2800c"
    assert any(e["from"] == "mtnr" and e["to"] == "yuvp" for e in rec["pipeline"]["edges"])
    impact = report["impact"]["uc-cam-recording-e2800c"]
    assert impact and all("msnr" in line for line in impact)
    assert all("msnr" not in (v.get("node_configs") or {}) for v in rec["variants"])


def test_pipeline_change_without_prune_fails_with_impact_list(scratch_root: Path):
    for sub in ("platforms", "projects"):
        shutil.copytree(EXAMPLE_2800 / sub, scratch_root / sub, dirs_exist_ok=True)
    overlay_path = scratch_root / "projects/e2800-concept/scenarios/uc-cam-recording-e2700/overlay.yaml"
    overlay = yamlio.load(overlay_path)
    overlay["prune_missing_nodes"] = False
    yamlio.dump(overlay_path, overlay)
    with pytest.raises(AuthoringError, match="node_configs.msnr"):
        compile_project(scratch_root, "e2800-concept")


# --- architecture knobs (crop strategy / EIS margin / pyramid L0) -----------

def _e2700_recording(root: Path) -> dict:
    return _docs(compile_project(root, "sm-s957b"))["uc-cam-recording-e2700"]


def test_byrp_bcrop_shrinks_the_chain_to_the_eis_window():
    rec = _e2700_recording(AUTHORING)
    base = _variant(rec, "cam-rec-r1-uhd30-vdis")
    bcrop = _variant(rec, "cam-rec-r1-uhd30-vdis-bcrop")
    # baseline (mcsc_crop): full sensor through the chain, untouched
    assert "bcrop_out" not in base["size_overrides"]
    assert base["node_configs"]["mtnr"]["sim"]["width"] == 4080
    # bcrop: 4080x2296 * 115/125 -> 3753.6 (align 16) x 2112.3 (align 2)
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
    # new variants inherit their parent's SW task set (no front/dual tasks leak in)
    tasks = lambda v: sorted(k for k, c in v["node_configs"].items() if "sw_timing" in c)  # noqa: E731
    assert tasks(bcrop) == tasks(base)


def test_pyramid_l0_skip_removes_only_the_l0_level():
    rec = _e2700_recording(AUTHORING)
    v = _variant(rec, "cam-rec-r1-uhd30-vdis-bcrop-l0skip")
    assert v["topology_patch"]["remove_edges"] == [{"from": "mlsc", "to": "mtnr", "buffer": "PYRAMID_L0"}]
    fhd = _variant(rec, "cam-rec-r1-fhd30-vdis-bcrop")   # parent's remove_edges kept, nothing appended
    assert {"from": "mlsc", "to": "mtnr", "buffer": "PYRAMID_L0"} not in fhd["topology_patch"]["remove_edges"]


def test_bcrop_without_eis_keeps_full_sensor_fov(scratch_root: Path):
    overlay_path = scratch_root / "projects/sm-s957b/scenarios/uc-cam-recording-e2600/overlay.yaml"
    overlay = yamlio.load(overlay_path)
    overlay["variants"]["add"].append({"id": "sdr-bcrop", "extends": "cam-rec-r1-uhd30-sdr",
                                       "design_conditions": {"crop_strategy": "byrp_bcrop"}})
    yamlio.dump(overlay_path, overlay)
    v = _variant(_e2700_recording(scratch_root), "sdr-bcrop")
    assert "eis" in v["routing_switch"]["disabled_nodes"]
    assert v["size_overrides"]["bcrop_out"] == "4080x2296"
    assert v["design_conditions"]["eis_margin_pct"] == 25


# --- bidirectional transition -----------------------------------------------

def test_sync_to_fixture_is_idempotent(tmp_path: Path):
    from scenario_db.authoring.cli import sync_to_fixture

    out = tmp_path / "fixture2700"
    first = sync_to_fixture(AUTHORING, "sm-s957b", out)
    assert first["added"] and not first["updated"]
    second = sync_to_fixture(AUTHORING, "sm-s957b", out)
    assert not second["added"] and not second["updated"]
    assert sync_to_fixture(AUTHORING, "sm-s947b", FIXTURE, dry_run=True)["updated"] == []


def test_fixture_with_knob_variants_decompiles_and_recompiles(scratch_root: Path, tmp_path: Path):
    from scenario_db.authoring.cli import sync_to_fixture
    from scenario_db.authoring.tree import decompile_fixture

    out = tmp_path / "fixture2700"
    sync_to_fixture(scratch_root, "sm-s957b", out)
    knobs_src = scratch_root / "projects/sm-s947b/scenarios/uc-cam-recording-e2600/knobs.yaml"
    knobs_dst = scratch_root / "projects/rt2700/scenarios/uc-cam-recording-e2700/knobs.yaml"
    knobs_dst.parent.mkdir(parents=True)
    shutil.copyfile(knobs_src, knobs_dst)
    decompile_fixture(out, scratch_root, "rt2700-platform", "rt2700")
    assert knobs_dst.exists()                      # hand-authored file survives decompile
    assert check_against(scratch_root, "rt2700", out) == []
