"""Exynos2700 authoring cases used by docs/guides/import/authoring-exynos2700-guide-ko.md.

Each test writes the guide's example files into a scratch copy of authoring/ and checks the
compiled documents (and, where it matters, that the result simulates).
"""

from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from scenario_db.authoring import yamlio
from scenario_db.authoring.errors import AuthoringError
from scenario_db.authoring.patch import deep_merge
from scenario_db.authoring.tree import compile_project
from scenario_db.authoring.validate import validate_documents

REPO = Path(__file__).resolve().parents[3]
AUTHORING = REPO / "authoring"
P7 = "platforms/exynos2700/patches"
UC = "projects/sm-s957b/scenarios/uc-cam-recording-e2600"
REC = "uc-cam-recording-e2700"


INHERITED = Path(__file__).parent / "fixtures" / "inherited_2700"
# Exynos2600 docs added after the 2700 eject (2026-10: v2-vf / mif-linear / CPU topology profile).
# The ejected 2700 does not take them; parent_diff reports such additions.
POST_EJECT_2600 = (
    "platforms/exynos2600/docs/00_hw/pmp-exynos2600-v2.yaml",
    "projects/sm-s947b/docs/00_hw/simcfg-proj-sm-s947b-v2.yaml",
)
# Exynos2600 IP docs edited after the eject (2026-10: SBWC declared on the MLSC -> MTNR L0/L1 DMA ports,
# synthetic MTNR LowPower mode). The inherited 2700 snapshot predates them -> stripped back here.
POST_EJECT_EDITED_2600 = (
    "platforms/exynos2600/docs/00_hw/ip-mlsc-is-v15-s5e9965.yaml",
    "platforms/exynos2600/docs/00_hw/ip-mtnr-is-v15-s5e9965.yaml",
)
# 2026-10: SAMPLE GPU V-f / leakage (clock-residency GPU power estimate) added to the 2600 GPU IP only.
POST_EJECT_GPU_2600 = "platforms/exynos2600/docs/00_hw/ip-gpu-s5e9965.yaml"
# 2026-10-11: SAMPLE unit power (MLSC / GDC / VPS), MFC LowPower mode and SBWC lossless typical_ratio on the
# 2600 platform only (lever analysis). The inherited 2700 snapshot predates them -> stripped back here.
POST_EJECT_SAMPLE_POWER_2600 = tuple(f"platforms/exynos2600/docs/00_hw/{n}.yaml" for n in (
    "ip-mlsc-is-v15-s5e9965", "ip-gdc-is-v15-s5e9965", "ip-vps-is-v15-s5e9965"))
POST_EJECT_MFC_2600 = "platforms/exynos2600/docs/00_hw/ip-mfc-s5e9965.yaml"
POST_EJECT_SOC_2600 = "platforms/exynos2600/docs/00_hw/soc-exynos2600.yaml"
# 2026-10: review_policy (throughput / power reference / thermal watch) added to the 2600 project only.
POST_EJECT_PROJECT_2600 = "projects/sm-s947b/project.yaml"


def _strip_post_eject(path: Path) -> None:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    caps = doc["capabilities"]
    caps.pop("supported_features", None)
    for mod in (caps.get("properties") or {}).get("modules") or []:
        mod.pop("supported_compressions", None)
    (caps.get("sim") or {}).get("modes", {}).pop("LowPower", None)
    caps["operating_modes"] = [m for m in caps.get("operating_modes") or [] if m.get("id") != "LowPower"]
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """Scratch authoring tree with Exynos2700 in its inherited (patch/overlay) form.

    The repository's exynos2700 / sm-s957b are ejected (complete files, edited directly);
    these tests exercise the derived-project mechanics (patch operators, overlays, clone)
    on the same content as it was before the eject (fixtures/inherited_2700)."""
    r = tmp_path / "authoring"
    shutil.copytree(AUTHORING, r, ignore=shutil.ignore_patterns("examples"))
    for sub in ("platforms/exynos2700", "projects/sm-s957b"):
        shutil.rmtree(r / sub)
        shutil.copytree(INHERITED / sub, r / sub)
    for doc in POST_EJECT_2600:   # parent docs added after the eject are not part of the 2700 snapshot
        (r / doc).unlink(missing_ok=True)
    for doc in POST_EJECT_EDITED_2600:
        _strip_post_eject(r / doc)
    gpu = r / POST_EJECT_GPU_2600
    gdoc = yaml.safe_load(gpu.read_text(encoding="utf-8"))
    for key in ("vf_table_sample", "leakage_sample"):
        gdoc["capabilities"]["power_model"].pop(key, None)
    gpu.write_text(yaml.safe_dump(gdoc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    for rel in POST_EJECT_SAMPLE_POWER_2600:
        path = r / rel
        sdoc = yaml.safe_load(path.read_text(encoding="utf-8"))
        sdoc["capabilities"]["sim"].pop("unit_power_mw_mp", None)
        path.write_text(yaml.safe_dump(sdoc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    mfc = r / POST_EJECT_MFC_2600
    mdoc = yaml.safe_load(mfc.read_text(encoding="utf-8"))
    mdoc["capabilities"]["sim"]["modes"].pop("LowPower", None)
    mfc.write_text(yaml.safe_dump(mdoc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    soc = r / POST_EJECT_SOC_2600
    sodoc = yaml.safe_load(soc.read_text(encoding="utf-8"))
    for mode in sodoc["compression_modes"].values():
        mode.pop("typical_ratio", None)
        mode.pop("note", None)
    soc.write_text(yaml.safe_dump(sodoc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    proj = r / POST_EJECT_PROJECT_2600
    pdoc = yaml.safe_load(proj.read_text(encoding="utf-8"))
    (pdoc["document"].get("globals") or {}).pop("review_policy", None)
    proj.write_text(yaml.safe_dump(pdoc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return r


def _compile(root: Path) -> dict[str, dict]:
    report = compile_project(root, "sm-s957b")
    assert validate_documents(report["documents"])["errors"] == []
    return {d.data["id"]: d.data for d in report["documents"] if isinstance(d.data, dict) and "id" in d.data}


def _variant(doc: dict, vid: str) -> dict:
    return next(v for v in doc["variants"] if v["id"] == vid)


def _overlay(root: Path) -> dict:
    return yamlio.load(root / UC / "overlay.yaml")


# --- patch operators ----------------------------------------------------------------------

def test_list_operators_remove_and_items():
    base = {"modules": [{"name": "A", "c": [1]}, {"name": "B"}], "edges": [{"from": "x", "to": "y", "t": 1},
                                                                         {"from": "x", "to": "z"}], "n": ["eis", "gdc"]}
    out = deep_merge(base, {
        "$remove": {"edges": [{"from": "x", "to": "y"}], "n": ["eis"]},
        "$items": {"modules": {"by": "name", "patch": {"A": {"c": [2]}}, "remove": ["B"], "add": [{"name": "C"}]}},
    })
    assert out["modules"] == [{"name": "A", "c": [2]}, {"name": "C"}]
    assert out["edges"] == [{"from": "x", "to": "z"}] and out["n"] == ["gdc"]
    with pytest.raises(AuthoringError, match="unknown"):
        deep_merge(base, {"$items": {"modules": {"by": "name", "patch": {"Z": {}}}}})
    with pytest.raises(AuthoringError, match="duplicate"):
        deep_merge(base, {"$items": {"modules": {"by": "name", "add": [{"name": "A"}]}}})
    with pytest.raises(AuthoringError, match="cannot change"):
        deep_merge(base, {"$items": {"modules": {"by": "name", "patch": {"A": {"name": "B"}}}}})
    with pytest.raises(AuthoringError, match="duplicate"):
        deep_merge({'modules': [{'name': 'A'}, {'name': 'A'}]},
                   {'$items': {'modules': {'by': 'name', 'patch': {'A': {'c': [2]}}}}})


# --- 1. IP: unit power / ppc / mode / DMA port / compression -------------------------------

def test_ip_patch_mode_dma_port_and_compression(root: Path):
    yamlio.dump(root / P7 / "ip-mcsc-is-v15-s5e9975.yaml", {
        "capabilities": {
            "sim": {"source": "exynos2700_arch_rev1", "modes": {
                "Normal": {"ppc": 8.0, "unit_power_mw_mp": 1.2},
                "LowPower": {"unit_power_mw_mp": 0.9, "ppc": 8.0, "idc": 0.0, "vdd": "VDD_CAM", "dvfs_group": "CAM",
                             "substitutes": ["Normal"], "iq_eval": "required", "label": "MCSC low power"},
            }},
            "operating_modes": [{"id": "Normal"}, {"id": "SBWC"}, {"id": "HDR10P"}, {"id": "LowPower"}],
            "properties": {"$items": {"modules": {
                "by": "name",
                "patch": {"MCSC_WDMA_W1": {"supported_compressions": ["COMP_OFF", "COMP_YUV_LOSSLESS"]}},
                "remove": ["MCSC_WDMA_W4"],
                "add": [{"name": "MCSC_WDMA_W5", "type": "DMA", "direction": "write",
                         "supported_compressions": ["COMP_OFF"]}],
            }}},
        },
    })
    ip = _compile(root)["ip-mcsc-is-v15-s5e9975"]
    modes = ip["capabilities"]["sim"]["modes"]
    assert modes["Normal"] == {"unit_power_mw_mp": 1.2, "idc": 0.0, "ppc": 8.0, "vdd": "VDD_CAM", "dvfs_group": "CAM"}
    assert modes["LowPower"]["substitutes"] == ["Normal"]
    mods = {m["name"]: m for m in ip["capabilities"]["properties"]["modules"]}
    assert "MCSC_WDMA_W4" not in mods and mods["MCSC_WDMA_W5"]["supported_compressions"] == ["COMP_OFF"]
    assert mods["MCSC_WDMA_W1"]["supported_compressions"] == ["COMP_OFF", "COMP_YUV_LOSSLESS"]
    assert mods["MCSC_WDMA_W0"]["supported_compressions"][-1] == "COMP_YUV_LOSSY"   # untouched


def test_port_compression_limits_exploration(root: Path):
    """A DMA port that loses lossy support drops that buffer from lossy compression candidates."""
    from scenario_db.db.models.capability import IpCatalog
    from scenario_db.db.models.definition import Scenario, ScenarioVariant
    from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
    from scenario_db.db.repositories.variant_resolution import resolve_variant_from_rows
    from scenario_db.sim import arch_exploration as ax
    from scenario_db.sim.models import SimulationRunConfig

    def rows(docs):
        rec = docs[REC]
        sc = Scenario(id=REC, schema_version="2.2", project_ref=rec["project_ref"], metadata_=rec["metadata"],
                      pipeline=rec["pipeline"], size_profile=rec.get("size_profile"),
                      power_options=rec.get("power_options"), yaml_sha256="t")
        vr = {v["id"]: ScenarioVariant(scenario_id=REC, **deepcopy(v)) for v in rec["variants"]}
        cat = {i: IpCatalog(id=i, schema_version=d["schema_version"], category=d["category"],
                            hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="t")
               for i, d in docs.items() if d.get("kind") == "ip"}
        g = CanonicalScenarioGraph(scenario=sc, variant=resolve_variant_from_rows(vr, REC, "cam-rec-r1-uhd30-vdis"),
                                   ip_catalog=cat)
        # gdc_o declares no compression in the 2700 catalog: relax the endpoint-declaration rule so this
        # test isolates the per-port supported_compressions limit
        return {r["buffer"]: r for r in ax.compression_candidates(g, ax.CompressionAxis(require_declared=False), SimulationRunConfig())}

    before = rows(_compile(root))["MCSC_VIDEO"]
    assert before["selectable"] and before["mode"] == "COMP_YUV_LOSSY"
    yamlio.dump(root / P7 / "ip-mcsc-is-v15-s5e9975.yaml", {"capabilities": {"properties": {"$items": {"modules": {
        "by": "name", "patch": {"MCSC_WDMA_W1": {"supported_compressions": ["COMP_OFF", "COMP_YUV_LOSSLESS"]}}}}}}})
    after = rows(_compile(root))["MCSC_VIDEO"]
    assert not after["selectable"] and after["unsupported_ports"] == ["mcsc.MCSC_WDMA_W1"]
    assert "DMA port without COMP_YUV_LOSSY" in after["skip_reason"]


# --- 2. scenario: EIS on by default, sizes ------------------------------------------------

EIS_ON = {
    "note": "2700: EIS(VDIS) on for UHD60 PSM / portrait",
    "variants": ["cam-rec-r1-uhd60-psm", "cam-rec-r1-uhd30-portrait"],
    "patch": {
        "design_conditions": {"stabilization": "SWVDIS", "is_scenario": "IS_SCENARIO_SWVDIS"},
        "routing_switch": {"$remove": {"disabled_nodes": ["eis", "gdc_m", "gdc_o"]}},
        "topology_patch": {"$remove": {"add_edges": [{"from": "mcsc", "to": "dpu"}, {"from": "mcsc", "to": "mfc_enc"}]}},
    },
}


def test_eis_default_on_for_selected_variants(root: Path):
    ov = _overlay(root)
    ov["variants"]["patch_resolved"] = [EIS_ON]
    yamlio.dump(root / UC / "overlay.yaml", ov)
    rec = _compile(root)[REC]
    for vid in EIS_ON["variants"]:
        v = _variant(rec, vid)
        assert not {"eis", "gdc_m", "gdc_o"} & set(v["routing_switch"]["disabled_nodes"])
        assert not [e for e in (v.get("topology_patch") or {}).get("add_edges") or []
                    if e["from"] == "mcsc" and e["to"] in ("dpu", "mfc_enc")]
        assert v["design_conditions"]["stabilization"] == "SWVDIS"
    assert "eis" in _variant(rec, "cam-rec-r1-fhd120")["routing_switch"]["disabled_nodes"]   # untouched
    # the knob param rule follows: bcrop becomes a power option once EIS is on
    assert rec["power_options"]["knobs"]["crop_strategy"]["explore"]["when_node_enabled"] == "eis"


def test_patch_resolved_by_condition_and_typo_guard(root: Path):
    ov = _overlay(root)
    ov["variants"]["patch_resolved"] = [{"when": {"power_saving_mode": True}, "patch": {"design_conditions": {"x": 1}}}]
    yamlio.dump(root / UC / "overlay.yaml", ov)
    rec = _compile(root)[REC]
    assert sorted(v["id"] for v in rec["variants"] if v["design_conditions"].get("x") == 1) == [
        "cam-rec-r1-8k30-psm", "cam-rec-r1-uhd60-pro", "cam-rec-r1-uhd60-psm"]   # pro extends psm
    ov["variants"]["patch_resolved"] = [{"when": {"power_saving_mode": "yes"}, "patch": {}}]
    yamlio.dump(root / UC / "overlay.yaml", ov)
    with pytest.raises(AuthoringError, match="selects no variant"):
        compile_project(root, "sm-s957b")


UHD_FHD = ["cam-rec-r1-fhd30-vdis", "cam-rec-r1-uhd30-vdis", "cam-rec-r1-uhd60-psm"]


def test_sensor_crop_size_and_derived_pyramid(root: Path):
    """Variants carry literal size_overrides (sensor_full, pyramid_l*): change them per variant and
    let forced derived rules recompute the dependent anchors."""
    ov = _overlay(root)
    ov["variants"]["patch_resolved"] = [{"note": "2700 sensor crop 4000x2252", "variants": UHD_FHD,
                                         "patch": {"size_overrides": {"sensor_full": "4000x2252"}}}]
    ov["sizes"] = {"derived": {
        "mlsc_out": {"from": "sensor_full", "force": True},
        "pyramid_l0": {"from": "mlsc_out", "force": True},
        "pyramid_l1": {"from": "pyramid_l0", "scale": 0.5, "round": "ceil", "force": True},
        "pyramid_l2": {"from": "pyramid_l1", "scale": 0.5, "round": "ceil", "force": True},
        "pyramid_l3": {"from": "pyramid_l2", "scale": 0.5, "round": "ceil", "force": True},
        "pyramid_l4": {"from": "pyramid_l3", "scale": 0.5, "round": "ceil", "force": True},
    }}
    yamlio.dump(root / UC / "overlay.yaml", ov)
    rec = _compile(root)[REC]
    v = _variant(rec, "cam-rec-r1-uhd30-vdis")
    assert (v["node_configs"]["rgbp"]["sim"]["width"], v["node_configs"]["rgbp"]["sim"]["height"]) == (4000, 2252)
    so = v["size_overrides"]
    assert (so["mlsc_out"], so["pyramid_l1"], so["pyramid_l4"]) == ("4000x2252", "2000x1126", "250x141")
    eight = _variant(rec, "cam-rec-r1-8k30-psm")["size_overrides"]
    assert (eight["sensor_full"], eight["pyramid_l1"]) == ("7680x4620", "3840x2310")   # not selected: recomputed same


# --- 3. scenario add -----------------------------------------------------------------------

def test_scenario_include_and_clone(root: Path):
    pj = yamlio.load(root / "projects/sm-s957b/project.yaml")
    pj["scenarios"]["include"].append("uc-cam-preview-e2600")
    yamlio.dump(root / "projects/sm-s957b/project.yaml", pj)
    yamlio.dump(root / "projects/sm-s957b/scenarios/uc-cam-recording-night-e2700/overlay.yaml", {
        "kind": "authoring.scenario_overlay",
        "from": "uc-cam-recording-e2600",
        "scenario_patch": {"metadata": {"name": "Camera Recording (Night)"}},
        "variants": {
            "keep": ["cam-rec-r1-fhd30-night", "cam-rec-r1-uhd30-night"],
            "add": [
                {"id": "cam-rec-r1-fhd30-night", "extends": "cam-rec-r1-fhd30-vdis",
                 "design_conditions": {"night_mode": True}},
                {"id": "cam-rec-r1-uhd30-night", "extends": "cam-rec-r1-uhd30-vdis",
                 "design_conditions": {"night_mode": True}},
            ],
        },
    })
    docs = _compile(root)
    assert "uc-cam-preview-e2700" in docs
    night = docs["uc-cam-recording-night-e2700"]
    assert night["project_ref"] == "proj-sm-s957b" and night["metadata"]["name"] == "Camera Recording (Night)"
    assert night["metadata"]["canonical_usecase"] == "uc-cam-recording-night"
    assert [v["id"] for v in night["variants"]] == ["cam-rec-r1-fhd30-night", "cam-rec-r1-uhd30-night"]
    assert all(n["ip_ref"].endswith("s5e9975") for n in night["pipeline"]["nodes"])
    assert len(docs[REC]["variants"]) == 16    # the original scenario is unchanged
    from scenario_db.authoring.cli import write_worksheet
    write_worksheet(root, 'sm-s957b')
    worksheet = root / 'projects/sm-s957b/scenarios/uc-cam-recording-night-e2700/sw_timing.measured.yaml'
    assert worksheet.exists()
    assert yamlio.load(worksheet)['scenario'] == 'uc-cam-recording-night-e2700'


def test_clone_from_unknown_parent_fails(root: Path):
    yamlio.dump(root / "projects/sm-s957b/scenarios/uc-x-e2700/overlay.yaml", {"from": "uc-nope-e2600"})
    with pytest.raises(AuthoringError, match="not a parent scenario"):
        compile_project(root, "sm-s957b")


# --- 4. sensor ------------------------------------------------------------------------------

def test_sensor_timing_mode_and_variant_sensor_mode(root: Path):
    mode = "cis_4sum_ln4_raw10_4080x2296_30fps_3993msps"
    yamlio.dump(root / P7 / "sensortiming-s5kgng-seta-19p2-s5e9975.yaml", {
        "revision": "2700-evt0-20261001",
        "modes": {mode: {"line_length_pck": 15000, "source": {"basis": "2700 EVT0 setfile", "path": "is-cis-gng-2700.h"}}},
    })
    yamlio.dump(root / P7 / "ip-sensor-gng-s5e9975.yaml", {"capabilities": {"properties": {"modes": {
        "mode0": {"sensor_mipi_speed": 4.5}}}}})
    ov = _overlay(root)
    ov["variants"]["patch_resolved"] = [{"variants": ["cam-rec-r1-uhd30-vdis"], "patch": {
        "node_configs": {"sensor_rear": {"selected_mode": "cis_4sum_ln2_raw10_4080x2296_60fps_3993msps"}}}}]
    yamlio.dump(root / UC / "overlay.yaml", ov)
    docs = _compile(root)
    t = docs["sensortiming-s5kgng-seta-19p2-s5e9975"]
    assert t["revision"] == "2700-evt0-20261001" and t["modes"][mode]["line_length_pck"] == 15000
    assert t["modes"][mode]["frame_length_lines"]          # other fields kept
    assert docs["ip-sensor-gng-s5e9975"]["capabilities"]["properties"]["modes"]["mode0"]["sensor_mipi_speed"] == 4.5
    assert _variant(docs[REC], "cam-rec-r1-uhd30-vdis")["node_configs"]["sensor_rear"]["selected_mode"].startswith(
        "cis_4sum_ln2")
    # Exynos2600 is untouched
    base = {d.data["id"]: d.data for d in compile_project(root, "sm-s947b")["documents"]
            if isinstance(d.data, dict) and "id" in d.data}
    assert base["sensortiming-s5kgng-seta-19p2"]["modes"][mode]["line_length_pck"] != 15000


def test_eis_enabled_variant_simulates_with_eis_stage(root: Path):
    from scenario_db.db.models.capability import IpCatalog
    from scenario_db.db.models.definition import Scenario, ScenarioVariant
    from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
    from scenario_db.db.repositories.variant_resolution import resolve_variant_from_rows
    from scenario_db.sim import arch_exploration as ax
    from scenario_db.sim.models import DVFSTable

    ov = _overlay(root)
    ov["variants"]["patch_resolved"] = [EIS_ON]
    yamlio.dump(root / UC / "overlay.yaml", ov)
    docs = _compile(root)
    rec = docs[REC]
    sc = Scenario(id=REC, schema_version="2.2", project_ref=rec["project_ref"], metadata_=rec["metadata"],
                  pipeline=rec["pipeline"], size_profile=rec.get("size_profile"),
                  power_options=rec.get("power_options"), yaml_sha256="t")
    rows = {v["id"]: ScenarioVariant(scenario_id=REC, **deepcopy(v)) for v in rec["variants"]}
    cat = {i: IpCatalog(id=i, schema_version=d["schema_version"], category=d["category"], hierarchy=d["hierarchy"],
                        capabilities=d["capabilities"], yaml_sha256="t") for i, d in docs.items() if d.get("kind") == "ip"}
    dvfs = {k: DVFSTable.model_validate(v) for k, v in docs["dvfs-exynos2700-sample-v0"]["domains"].items()}
    g = CanonicalScenarioGraph(scenario=sc, variant=resolve_variant_from_rows(rows, REC, "cam-rec-r1-uhd60-psm"),
                               ip_catalog=cat)
    r = ax.explore_variant(g, ax.ArchExplorationSpec(), dvfs_tables=dvfs)
    assert r["eis_on"] and r["spec_ok"]
    assert "knob:crop_strategy=byrp_bcrop" in {i for x in r["power_options"]["results"] for i in x["items"]}


def test_new_ip_rebinding_soc_list_and_compression_defaults(root: Path):
    yamlio.dump(root / "platforms/exynos2700/docs/00_hw/ip-mfc-v2-s5e9975.yaml", {
        "id": "ip-mfc-v2-s5e9975", "schema_version": "2.2", "kind": "ip", "category": "codec",
        "hierarchy": {"type": "simple"},
        "capabilities": {
            "sim": {"hw_name": "MFC", "source": "exynos2700_arch_rev1", "modes": {
                "Normal": {"unit_power_mw_mp": 0.8, "ppc": 8.0, "idc": 0.0, "vdd": "VDD_MFC", "dvfs_group": "MFC"}}},
            "supported_features": {"compression": ["COMP_OFF", "COMP_LOSSLESS"]},
            "properties": {"modules": [{"name": "MFC_RDMA", "type": "DMA", "direction": "read",
                                        "supported_compressions": ["COMP_OFF", "COMP_YUV_LOSSLESS"]}]},
        },
        "compatible_soc": ["soc-exynos2700"],
    })
    yamlio.dump(root / P7 / "soc-exynos2700.yaml", {
        "compression_modes": {"COMP_YUV_LOSSY": {"comp_ratio": 0.45}},
        "$items": {"ips": {"by": "ref", "add": [{"ref": "ip-mfc-v2-s5e9975", "instance_count": 1}]}},
    })
    ov = _overlay(root)
    ov["pipeline"] = {"set_nodes": {"mfc_enc": {"ip_ref": "ip-mfc-v2-s5e9975"}}}
    ov["scenario_patch"] = {"pipeline": {"buffers": {"MCSC_VIDEO": {"compression": "COMP_YUV_LOSSLESS"}}}}
    ov["variants"]["keep"].append("cam-rec-r1-uhd30-hdr10")
    ov["variants"]["add"].append({"id": "cam-rec-r1-uhd30-log", "extends": "cam-rec-r1-uhd30-vdis",
                                  "design_conditions": {"camera_mode": "log_video", "hdr": "LOG"}})
    ov["variants"]["keep"].append("cam-rec-r1-uhd30-log")
    yamlio.dump(root / UC / "overlay.yaml", ov)
    docs = _compile(root)
    soc = docs["soc-exynos2700"]
    assert soc["compression_modes"]["COMP_YUV_LOSSY"] == {"compressor": "SBWC", "comp_ratio": 0.45}
    assert {"ref": "ip-mfc-v2-s5e9975", "instance_count": 1} in soc["ips"]
    rec = docs[REC]
    assert next(n for n in rec["pipeline"]["nodes"] if n["id"] == "mfc_enc")["ip_ref"] == "ip-mfc-v2-s5e9975"
    assert rec["pipeline"]["buffers"]["MCSC_VIDEO"]["compression"] == "COMP_YUV_LOSSLESS"
    assert [v["id"] for v in rec["variants"]][-2:] == ["cam-rec-r1-uhd30-hdr10", "cam-rec-r1-uhd30-log"]


def test_inherited_fixture_compiles_to_the_ejected_project(root: Path):
    """fixtures/inherited_2700 and the ejected authoring/ produce the same documents."""
    from scenario_db.authoring.patch import diff_paths

    inherited = {d.rel: d.data for d in compile_project(root, "sm-s957b")["documents"]}
    ejected = {d.rel: d.data for d in compile_project(AUTHORING, "sm-s957b")["documents"]}
    assert set(inherited) == set(ejected)
    assert [r for r in inherited if diff_paths(inherited[r], ejected[r])] == []


def test_eject_and_parent_diff(root: Path):
    from scenario_db.authoring.eject import eject_project, parent_diff

    rep = eject_project(root, "sm-s957b", commit="test")
    assert rep["scenarios"] and rep["measured_kept"] == [REC]
    pj = yamlio.load(root / "projects/sm-s957b/project.yaml")
    assert "extends" not in pj and pj["document"]["id"] == "proj-sm-s957b"
    assert not (root / "platforms/exynos2700/patches").exists()
    assert (root / "platforms/exynos2700/docs/00_hw/ip-mcsc-is-v15-s5e9975.yaml").exists()
    sdir = root / f"projects/sm-s957b/scenarios/{REC}"
    assert {p.name for p in sdir.iterdir()} >= {"scenario.yaml", "variants.yaml", "sizes.yaml", "sw_timing.yaml",
                                              "knobs.yaml", "sw_timing.measured.yaml"}
    assert parent_diff(root, "sm-s957b")["changed"] == []
    # a later 2600 change shows up, mapped to the 2700 id
    ip = root / "platforms/exynos2600/docs/00_hw/ip-mcsc-is-v15-s5e9965.yaml"
    ip.write_text(ip.read_text(encoding="utf-8").replace("unit_power_mw_mp: 1.5", "unit_power_mw_mp: 1.7", 1),
                  encoding="utf-8")
    changed = parent_diff(root, "sm-s957b")["changed"]
    assert changed == [{"doc": "ip-mcsc-is-v15-s5e9975", "parent": "ip-mcsc-is-v15-s5e9965",
                        "diff": ["~ capabilities.sim.modes.Normal.unit_power_mw_mp"]}]
    with pytest.raises(AuthoringError, match="nothing to eject"):
        eject_project(root, "sm-s957b")


def test_parent_diff_reports_variant_removal_and_accepts_it(root: Path):
    from scenario_db.authoring.eject import accept_parent, eject_project, parent_diff

    eject_project(root, "sm-s957b")
    path = root / "projects/sm-s947b/scenarios/uc-cam-recording-e2600/variants.yaml"
    variants = yamlio.load(path)
    parents = {v.get("extends") for v in variants}
    removed = next(v["id"] for v in reversed(variants) if v["id"] not in parents)
    yamlio.dump(path, [v for v in variants if v["id"] != removed])
    change = next(c for c in parent_diff(root, "sm-s957b")["changed"] if c["doc"] == REC)
    assert change["variants_removed"] == [removed]
    assert change["variants_changed"] == []
    accept_parent(root, "sm-s957b")
    assert parent_diff(root, "sm-s957b")["changed"] == []


def test_eject_restores_both_directories_after_publish_failure(root: Path, monkeypatch):
    from scenario_db.authoring.eject import eject_project

    def contents():
        return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    before = contents()
    original_rename = Path.rename

    def fail_project_publish(source, destination):
        if (source.name == "sm-s957b" and source.parent.name == "projects"
                and Path(destination) == root / "projects/sm-s957b"):
            raise PermissionError("injected second-directory publish failure")
        return original_rename(source, destination)

    monkeypatch.setattr(Path, "rename", fail_project_publish)
    with pytest.raises(AuthoringError, match="original files restored"):
        eject_project(root, "sm-s957b")
    assert contents() == before
    assert not list(root.glob(".eject-backup-*"))


def test_accept_parent_on_non_ejected_project_is_a_cli_error(root: Path, capsys):
    from scenario_db.authoring.cli import main

    assert main(["--root", str(root), "parent-diff", "sm-s957b", "--accept"]) == 2
    assert "not ejected" in capsys.readouterr().err
