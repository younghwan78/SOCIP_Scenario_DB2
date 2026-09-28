"""Eject a derived project: write every inherited document as an editable source file.

A derived project (``extends`` + rename + patches + overlays) is compact but hard to
edit without knowing what it inherits. ``eject`` turns it into a root platform/project
whose files hold the complete compiled content, so a change is a direct edit:

    authoring/platforms/<platform>/docs/**            every HW / sensor / SW document
    authoring/projects/<key>/project.yaml             root project (document inline)
    authoring/projects/<key>/docs/**                  project documents (sim config ...)
    authoring/projects/<key>/scenarios/<uc id>/       scenario.yaml, variants.yaml, sizes.yaml,
                                                      sw_timing.yaml, knobs.yaml,
                                                      sw_timing.measured.yaml (kept)
    authoring/projects/<key>/ejected-from.yaml        parent ids + content hashes at eject time

Patches and overlays are baked into those files and removed. The compiled output is
unchanged (verified before anything is written). Afterwards the parent no longer
propagates; ``parent-diff`` lists parent documents / variants that changed since the eject.
"""

from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from scenario_db.authoring import yamlio
from scenario_db.authoring.errors import AuthoringError
from scenario_db.authoring.patch import diff_paths
from scenario_db.authoring.rename import rename_value
from scenario_db.authoring.scenario import compile_usecase, decompile_usecase
from scenario_db.authoring.tree import compile_project, load_project

EJECT_FILE = "ejected-from.yaml"


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def _docs(report: dict) -> dict[str, Any]:
    return {d.rel: d for d in report["documents"]}


def _usecase_hashes(doc: dict) -> dict[str, Any]:
    return {"base": _sha({k: v for k, v in doc.items() if k != "variants"}),
            "variants": {v["id"]: _sha(v) for v in doc.get("variants") or []}}


def _parent_snapshot(root: Path, parent_key: str, id_map: dict[str, str]) -> dict[str, Any]:
    """Parent compiled docs keyed by the CHILD id they map to (hashes of the parent content)."""
    out: dict[str, Any] = {}
    for d in compile_project(root, parent_key)["documents"]:
        if not isinstance(d.data, dict) or "id" not in d.data:
            continue
        pid = d.data["id"]
        cid = id_map.get(pid, pid)
        entry: dict[str, Any] = {"parent": pid}
        if d.data.get("kind") == "scenario.usecase":
            entry |= _usecase_hashes(d.data)
        else:
            entry["sha"] = _sha(d.data)
        out[cid] = entry
    return out


def eject_project(root: Path, key: str, *, commit: str | None = None) -> dict[str, Any]:
    root = Path(root)
    spec = yamlio.load(root / "projects" / key / "project.yaml")
    if not spec.get("extends"):
        raise AuthoringError(f"project '{key}' does not extend another project: nothing to eject")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "authoring"
        shutil.copytree(root, work)
        report = _eject_in(work, key, commit)
        for sub in (f"platforms/{report['platform']}", f"projects/{key}"):
            shutil.rmtree(root / sub)
            shutil.copytree(work / sub, root / sub)
    return report


def _eject_in(root: Path, key: str, commit: str | None) -> dict[str, Any]:
    before = compile_project(root, key)
    bundle = load_project(root, key)
    spec = yamlio.load(root / "projects" / key / "project.yaml")
    parent_key = spec["extends"]
    pdir = root / "platforms" / bundle.platform_id
    jdir = root / "projects" / key
    pspec = yamlio.load(pdir / "platform.yaml")
    users = [p.parent.name for p in (root / "projects").glob("*/project.yaml")
             if p.parent.name != key and (yamlio.load(p) or {}).get("platform") == bundle.platform_id]
    if pspec.get("extends") and users:
        raise AuthoringError(f"platform '{bundle.platform_id}' is also used by {users}; eject would change them")
    id_map = dict(bundle.report.get("id_map") or {})
    snapshot = _parent_snapshot(root, parent_key, id_map)

    # ---- platform: all docs verbatim, no inheritance
    platform_parent = pspec.get("extends")
    if platform_parent:
        shutil.rmtree(pdir)
        pdir.mkdir(parents=True)
        for d in bundle.platform_docs:
            target = pdir / "docs" / d.rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if d.data is None or d.raw is not None:
                target.write_bytes(d.raw if d.raw is not None else b"")
            else:
                yamlio.dump(target, d.data)
        yamlio.dump(pdir / "platform.yaml", {
            "kind": "authoring.platform", "id": bundle.platform_id, "soc_id": pspec.get("soc_id"),
            "description": pspec.get("description"),
            "ejected_from": {"platform": platform_parent, "rename": pspec.get("rename") or [],
                             "rename_suffix": pspec.get("rename_suffix") or []},
        }, header="Root platform (ejected: every document is a complete, editable file under docs/).\n"
                  "Edit docs/00_hw, docs/00_sensor, docs/01_sw directly. The parent platform no longer\n"
                  f"propagates; `python -m scenario_db.authoring parent-diff {key}` lists its changes.")

    # ---- project: root with inline document, docs, full scenario sources
    measured: dict[str, Path] = {}
    for uc in bundle.scenarios:
        origin = bundle.origins.get(uc, uc)
        for name in (origin, uc):
            m = jdir / "scenarios" / name / "sw_timing.measured.yaml"
            if m.exists() and uc not in measured:
                measured[uc] = m
    kept = {uc: yamlio.load(m) for uc, m in measured.items()}
    for sub in ("scenarios", "patches", "docs"):
        if (jdir / sub).exists():
            shutil.rmtree(jdir / sub)
    for d in bundle.project_docs:
        target = jdir / "docs" / d.rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if d.data is None:
            target.write_bytes(d.raw or b"")
        else:
            yamlio.dump(target, d.data)
    for uc, src in bundle.scenarios.items():
        sdir = jdir / "scenarios" / uc
        sdir.mkdir(parents=True, exist_ok=True)
        knobs = copy.deepcopy(src.get("knobs") or {})
        if knobs:
            yamlio.dump(sdir / "knobs.yaml", knobs,
                        header="Architecture knobs (hand-authored; decompile keeps this file).\n"
                               "`explore` = power-saving option for combination exploration.")
        if src.get("sizes"):   # keep the reviewed node->anchor bindings (decompile would re-infer them)
            yamlio.dump(sdir / "sizes.yaml", src["sizes"])
        decompile_usecase(compile_usecase(src), sdir)
        if uc in kept:
            yamlio.dump(sdir / "sw_timing.measured.yaml", kept[uc],
                        header="Measured SW timing slots (applied on top of sw_timing.yaml at compile).\n"
                               "`timing: null` = pending. Later entries win.")
    yamlio.dump(jdir / "project.yaml", {
        "kind": "authoring.project", "key": key, "platform": bundle.platform_id,
        "document": bundle.project,
    }, header="Root project (ejected from a derived project). Scenario sources under scenarios/<uc id>/\n"
              "are complete: edit variants.yaml / scenario.yaml / sizes.yaml / sw_timing.yaml / knobs.yaml.")
    yamlio.dump(jdir / EJECT_FILE, {
        "kind": "authoring.eject_record",
        "project": key, "parent_project": parent_key,
        "platform": bundle.platform_id, "parent_platform": platform_parent,
        "date": _dt.date.today().isoformat(), "commit": commit,
        "id_map": dict(sorted(id_map.items())),
        "parent_docs": snapshot,
    }, header="GENERATED by `authoring eject` - parent ids and content hashes at eject time.\n"
              "Used by `authoring parent-diff` to find parent changes after the eject. Do not edit.")

    # ---- verify: identical compiled output
    after = compile_project(root, key)
    b, a = _docs(before), _docs(after)
    problems = sorted(set(b) ^ set(a))
    for rel in set(b) & set(a):
        x, y = b[rel], a[rel]
        if x.data is not None or y.data is not None:
            if diff_paths(x.data, y.data):
                problems.append(f"{rel}: {diff_paths(x.data, y.data)[:5]}")
        elif x.raw != y.raw:
            problems.append(f"{rel}: bytes differ")
    if problems:
        raise AuthoringError("eject would change the compiled output: " + "; ".join(problems[:10]))
    return {"project": key, "platform": bundle.platform_id, "parent_project": parent_key,
            "platform_docs": len(bundle.platform_docs), "project_docs": len(bundle.project_docs),
            "scenarios": {uc: len((src.get("variants") or [])) for uc, src in bundle.scenarios.items()},
            "measured_kept": sorted(kept), "documents": len(a)}


def accept_parent(root: Path, key: str) -> int:
    """Re-baseline: record the current parent hashes (after reviewing / porting parent-diff)."""
    rec_path = Path(root) / "projects" / key / EJECT_FILE
    rec = yamlio.load(rec_path)
    rec["parent_docs"] = _parent_snapshot(Path(root), rec["parent_project"], rec.get("id_map") or {})
    rec["accepted"] = _dt.date.today().isoformat()
    yamlio.dump(rec_path, rec, header="GENERATED by `authoring eject` / `parent-diff --accept` - parent ids and\n"
                                      "content hashes of the last reviewed parent state. Do not edit.")
    return len(rec["parent_docs"])


def parent_diff(root: Path, key: str, *, limit: int = 20) -> dict[str, Any]:
    """Parent documents / variants that changed since the eject, with the paths that now
    differ between the (renamed) parent and this project."""
    root = Path(root)
    rec_path = root / "projects" / key / EJECT_FILE
    if not rec_path.exists():
        raise AuthoringError(f"project '{key}' has no {EJECT_FILE}: not ejected")
    rec = yamlio.load(rec_path)
    id_map = rec.get("id_map") or {}
    then = rec.get("parent_docs") or {}
    parent = {d.data["id"]: d.data for d in compile_project(root, rec["parent_project"])["documents"]
              if isinstance(d.data, dict) and "id" in d.data}
    child = {d.data["id"]: d.data for d in compile_project(root, key)["documents"]
             if isinstance(d.data, dict) and "id" in d.data}
    out: dict[str, Any] = {"changed": [], "new_in_parent": [], "removed_in_parent": []}
    now_by_child = {id_map.get(pid, pid): pid for pid in parent}
    for cid, pid in sorted(now_by_child.items()):
        pdoc = rename_value(parent[pid], id_map)
        old = then.get(cid)
        if old is None:
            out["new_in_parent"].append({"parent": pid, "as": cid})
            continue
        if pdoc.get("kind") == "scenario.usecase":
            now = _usecase_hashes(parent[pid])
            base_changed = now["base"] != old.get("base")
            vchanged = sorted(v for v, h in now["variants"].items() if old.get("variants", {}).get(v) != h)
            if not (base_changed or vchanged):
                continue
            cdoc = child.get(cid) or {}
            cvars = {v["id"]: v for v in cdoc.get("variants") or []}
            pvars = {v["id"]: v for v in pdoc.get("variants") or []}
            item: dict[str, Any] = {"doc": cid, "parent": pid, "base_changed": base_changed,
                                    "variants_changed": vchanged, "in_project": {}}
            if base_changed and cdoc:
                item["base_diff"] = diff_paths({k: v for k, v in pdoc.items() if k != "variants"},
                                               {k: v for k, v in cdoc.items() if k != "variants"})[:limit]
            for vid in vchanged:
                if vid in cvars and vid in pvars:
                    item["in_project"][vid] = diff_paths(pvars[vid], cvars[vid])[:limit]
            out["changed"].append(item)
        elif _sha(parent[pid]) != old.get("sha"):
            item = {"doc": cid, "parent": pid}
            if cid in child:
                item["diff"] = diff_paths(pdoc, child[cid])[:limit]
            else:
                item["diff"] = ["(not in project)"]
            out["changed"].append(item)
    out["removed_in_parent"] = sorted(c for c in then if c not in now_by_child)
    return out
