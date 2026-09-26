"""One-off (2026-09-27): reduce Exynos2600 to the camera-recording KPI set.

* keeps 15 existing rear/dual variants, merges 2 APV variants from
  uc-cam-recording-apv-e2600 (apv_enc injected per variant, mfc_enc disabled)
* adds UHD30/60/120 Pro video (extra CPU task for histogram / equalizer overlay)
  and UHD120 APV — values marked assumed
* archives everything else (scenarios, variants, evidence) under
  authoring/archive/2026-09-27-scope-reduction/  (recoverable, not loaded)
Run once from implementation/:  python scripts/oneoff/scope_reduction_20260927.py
"""
from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path

import yaml

FX = Path("db_fixtures_Exynos2600_S26Plus")
ARCH = Path("authoring/archive/2026-09-27-scope-reduction")
REC = "uc-cam-recording-e2600"
APV = "uc-cam-recording-apv-e2600"

KEEP_REC = [
    "cam-rec-r1-fhd30-vdis", "cam-rec-r1-fhd60-supersteady", "cam-rec-r1-uhd30-vdis",
    "cam-rec-r1-uhd60-psm", "cam-rec-r1-8k30-psm", "cam-rec-r1-fhd120", "cam-rec-r1-fhd240",
    "cam-rec-r1-uhd120", "cam-rec-r1-fhd30-portrait", "cam-rec-r1-uhd30-portrait",
    "cam-rec-pip-fhd30", "cam-rec-pip-uhd30",
]
KEEP_APV = ["cam-rec-apv-uhd30-422-sdr", "cam-rec-apv-uhd60-422-sdr"]
PRO = [("cam-rec-r1-uhd30-pro", "cam-rec-r1-uhd30-vdis"), ("cam-rec-r1-uhd60-pro", "cam-rec-r1-uhd60-psm"),
       ("cam-rec-r1-uhd120-pro", "cam-rec-r1-uhd120")]
ASSUMED = "Assumed 2026-09-27 (scope reduction); replace with internal measurement."


def load(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def dump(p: Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")


def to_apv(v: dict, apv_node: dict, apv_cfg: dict) -> dict:
    """Swap the encoder of one expanded variant from MFC to APV."""
    v = copy.deepcopy(v)
    tp = v.setdefault("topology_patch", {})
    if not any(n.get("id") == "apv_enc" for n in tp.get("add_nodes") or []):
        tp.setdefault("add_nodes", []).append(copy.deepcopy(apv_node))
    for key in ("add_edges", "remove_edges"):
        for e in tp.get(key) or []:
            for end in ("from", "to"):
                if e.get(end) == "mfc_enc":
                    e[end] = "apv_enc"
            for pp in e.get("port_pairs") or []:
                if pp.get("dst") == "MFC_RDMA":
                    pp["dst"] = "APV_RDMA_FRAME"
    dis = v.setdefault("routing_switch", {}).setdefault("disabled_nodes", [])
    if "mfc_enc" not in dis:
        dis.append("mfc_enc")
    cfgs = v.setdefault("node_configs", {})
    mfc = cfgs.pop("mfc_enc", None) or {}
    cfg = copy.deepcopy(apv_cfg)
    if isinstance(mfc.get("sim"), dict):
        for k in ("width", "height"):
            if k in mfc["sim"]:
                cfg.setdefault("sim", {})[k] = mfc["sim"][k]
    cfgs["apv_enc"] = cfg
    return v


def main() -> None:
    rec = load(FX / "02_definition" / f"{REC}.yaml")
    apv = load(FX / "02_definition" / f"{APV}.yaml")
    rv = {v["id"]: v for v in rec["variants"]}
    av = {v["id"]: v for v in apv["variants"]}
    apv_node = next(n for n in apv["pipeline"]["nodes"] if n["id"] == "apv_enc")
    kept = [copy.deepcopy(rv[i]) for i in KEEP_REC]
    for i in KEEP_APV:
        v = av[i]
        kept.append(to_apv(v, apv_node, v["node_configs"]["apv_enc"]))
    # Pro video: same pipeline, extra CPU load for histogram / waveform / equalizer overlay
    for new_id, base in PRO:
        v = copy.deepcopy(rv[base])
        v["id"] = new_id
        dc = v.setdefault("design_conditions", {})
        dc.update({"camera_mode": "pro_video", "pro_video_overlay": "histogram+equalizer",
                   "pro_video_source": "assumed"})
        tp = v.setdefault("topology_patch", {})
        tp.setdefault("add_nodes", []).append({"id": "pro_scope", "ip_ref": "ip-cpu-s5e9965", "role": "sw_task", "instance_index": 0})
        tp.setdefault("add_edges", []).append({"from": "mcsc", "to": "pro_scope", "type": "control"})
        v.setdefault("node_configs", {})["pro_scope"] = {"sw_timing": {
            "min_ms": 2.0, "mean_ms": 3.0, "max_ms": 4.5, "value_source": "assumed", "source_note": ASSUMED}}
        v.setdefault("tags", []).append("pro-video")
        kept.append(v)
    # UHD120 APV
    base = av["cam-rec-apv-uhd60-422-sdr"]
    v = to_apv(rv["cam-rec-r1-uhd120"], apv_node, base["node_configs"]["apv_enc"])
    v["id"] = "cam-rec-apv-uhd120-422-sdr"
    dc = v["design_conditions"]
    for k, val in base["design_conditions"].items():
        if k.startswith("apv_") or k in ("encoder_hw", "hdr"):
            dc[k] = val
    dc["record_bitrate_mbps"] = float(base["design_conditions"].get("record_bitrate_mbps", 1000.0)) * 2
    dc["bitrate_source"] = "assumed"
    v.setdefault("tags", []).append("apv")
    kept.append(v)

    removed_rec = [i for i in rv if i not in KEEP_REC]
    removed_apv = [i for i in av if i not in KEEP_APV]
    # archive full original docs
    ARCH.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FX / "02_definition" / f"{REC}.yaml", ARCH / f"{REC}.orig.yaml")
    rec["variants"] = kept
    dump(FX / "02_definition" / f"{REC}.yaml", rec)
    # other scenarios -> archive
    moved_sc = []
    for p in sorted((FX / "02_definition").glob("uc-*.yaml")):
        if p.stem != REC:
            shutil.move(str(p), ARCH / p.name)
            moved_sc.append(p.stem)
    # evidence: re-point APV, archive removed
    keep_ids = {v["id"] for v in kept}
    moved_ev = []
    for p in sorted((FX / "03_evidence").glob("*.yaml")):
        t = p.read_text(encoding="utf-8")
        m = re.search(r"(?m)^variant_ref:\s*(\S+)", t)
        vid = m.group(1).strip("'\"") if m else None
        if vid not in keep_ids:
            (ARCH / "03_evidence").mkdir(exist_ok=True)
            shutil.move(str(p), ARCH / "03_evidence" / p.name)
            moved_ev.append(p.name)
            continue
        n = re.sub(r"(?m)^(\s*(?:scenario_ref|scenario_id):\s*)" + re.escape(APV) + r"\s*$", r"\g<1>" + REC, t)
        if n != t:
            p.write_text(n, encoding="utf-8", newline="")
    dump(ARCH / "MANIFEST.yaml", {
        "reason": "Scope reduction to camera-recording KPI set (Exynos2600 reference)",
        "kept_variants": [v["id"] for v in kept],
        "removed_variants": {REC: removed_rec, APV: removed_apv},
        "archived_scenarios": moved_sc, "archived_evidence": moved_ev,
    })
    print(len(kept), "variants kept;", len(moved_sc), "scenarios,", len(moved_ev), "evidence archived")


if __name__ == "__main__":
    main()
