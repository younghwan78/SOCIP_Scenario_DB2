"""Authoring tree: platform / project inheritance, decompile and compile.

Layout::

    authoring/
      platforms/<platform>/platform.yaml     kind: authoring.platform
      platforms/<platform>/docs/**           root platform: canonical HW/sensor/SW docs (verbatim)
      platforms/<platform>/patches/<id>.yaml child platform: deep-merge patch per (renamed) doc id
      projects/<project>/project.yaml        kind: authoring.project
      projects/<project>/docs/**             project-scoped docs (sim.config_profile ...)
      projects/<project>/scenarios/<uc-id>/  scenario sources (root) or overlay.yaml (child)
          sw_timing.measured.yaml            measured SW timing slots (any project)
"""

from __future__ import annotations

import copy
import fnmatch
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scenario_db.authoring import yamlio
from scenario_db.authoring.patch import deep_merge
from scenario_db.authoring.pipeline_ops import apply_overlay, prune_or_report_missing_nodes
from scenario_db.authoring.rename import apply_rules, build_id_map, rename_value
from scenario_db.authoring.scenario import (
    GENERATED_FILES,
    AuthoringError,
    variant_parents,
    apply_sw_measurements,
    compile_usecase,
    decompile_usecase,
    load_scenario_sources,
)

PROJECT_KINDS = {"project"}
PROJECT_DOC_KINDS = {"sim.config_profile"}
SCENARIO_KINDS = {"scenario.usecase"}
PLATFORM_DIRS = ("00_hw", "00_sensor", "01_sw")


@dataclass
class Doc:
    rel: str                      # output path relative to the canonical root
    data: Any = None              # parsed YAML (None for non-YAML files)
    raw: bytes | None = None      # verbatim content when unchanged

    @property
    def id(self) -> str | None:
        return self.data.get("id") if isinstance(self.data, dict) else None


@dataclass
class Bundle:
    platform_id: str
    platform_docs: list[Doc]
    platform_id_map: dict[str, str]
    project_key: str
    project: dict
    project_docs: list[Doc]
    scenarios: dict[str, dict]            # uc id -> compact sources
    measured: dict[str, dict] = field(default_factory=dict)
    overlays: dict[str, dict] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)
    origins: dict[str, str] = field(default_factory=dict)   # child uc id -> parent uc id (authoring dir name)


# ---------------------------------------------------------------------------
# decompile (canonical fixture dir -> root platform + root project)
# ---------------------------------------------------------------------------

def decompile_fixture(fixture_dir: Path, authoring_root: Path, platform_id: str,
                      project_key: str) -> dict[str, Any]:
    pdir = authoring_root / "platforms" / platform_id
    jdir = authoring_root / "projects" / project_key
    # Reject an invalid source or an inherited target before removing owned files.
    for spec_path in (pdir / "platform.yaml", jdir / "project.yaml"):
        if spec_path.exists() and (yamlio.load(spec_path) or {}).get("extends"):
            raise AuthoringError(f"cannot decompile into inherited target: {spec_path}")
    if not fixture_dir.is_dir():
        raise AuthoringError(f"fixture directory does not exist: {fixture_dir}")
    source_docs = [Doc(rel=p.relative_to(fixture_dir).as_posix(), data=yamlio.load(p))
                   for p in sorted(fixture_dir.rglob("*")) if p.is_file() and p.suffix in (".yaml", ".yml")]
    projects = [d for d in source_docs if isinstance(d.data, dict) and d.data.get("kind") == "project"]
    if len(projects) != 1:
        raise AuthoringError("decompile requires exactly one project document")
    from scenario_db.authoring.validate import validate_documents
    validation = validate_documents(source_docs)
    if validation["errors"]:
        raise AuthoringError("fixture invalid: " + "; ".join(validation["errors"][:10]))
    for stale in (pdir / "docs", jdir / "docs"):
        if not stale.resolve().is_relative_to(authoring_root.resolve()):
            raise AuthoringError(f"target outside authoring root: {stale}")
        if stale.exists():   # decompile owns these verbatim copies (root platform/project only)
            shutil.rmtree(stale)
    stats: dict[str, Any] = {"platform_docs": 0, "project_docs": 0, "scenarios": {}, "skipped": []}
    soc_id = None
    project_doc = None
    for path in sorted(fixture_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(fixture_dir).as_posix()
        top = rel.split("/")[0]
        if path.suffix not in (".yaml", ".yml"):
            if top in PLATFORM_DIRS:
                _copy(path, pdir / "docs" / rel)
                stats["platform_docs"] += 1
            else:
                stats["skipped"].append(rel)
            continue
        data = yamlio.load(path)
        kind = data.get("kind") if isinstance(data, dict) else None
        if kind in SCENARIO_KINDS:
            stats["scenarios"][data["id"]] = decompile_usecase(data, jdir / "scenarios" / data["id"])
        elif kind in PROJECT_KINDS:
            project_doc = data
        elif kind in PROJECT_DOC_KINDS:
            _copy(path, jdir / "docs" / rel)
            stats["project_docs"] += 1
        elif kind and top in PLATFORM_DIRS:
            if kind == "soc":
                soc_id = data["id"]
            _copy(path, pdir / "docs" / rel)
            stats["platform_docs"] += 1
        else:
            stats["skipped"].append(rel)
    if project_doc is None:
        raise AuthoringError(f"no kind: project document in {fixture_dir}")
    sdir = jdir / "scenarios"
    stats["stale_scenarios"] = []
    if sdir.exists():   # scenarios gone from the fixture: drop generated files, keep hand-authored ones
        for d in sorted(p for p in sdir.iterdir() if p.is_dir() and p.name not in stats["scenarios"]):
            for name in GENERATED_FILES:
                (d / name).unlink(missing_ok=True)
            stats["stale_scenarios"].append(d.name)
    yamlio.dump(pdir / "platform.yaml", {
        "kind": "authoring.platform", "id": platform_id, "soc_id": soc_id,
        "description": f"Decompiled from {fixture_dir.name}. docs/ holds canonical HW, sensor and SW catalog files.",
    })
    yamlio.dump(jdir / "project.yaml", {
        "kind": "authoring.project", "key": project_key, "platform": platform_id,
        "document": project_doc,
    })
    return stats


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


# ---------------------------------------------------------------------------
# load / resolve
# ---------------------------------------------------------------------------

def _read_docs(root: Path) -> list[Doc]:
    docs: list[Doc] = []
    if not root.exists():
        return docs
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            raw = path.read_bytes()
            data = yamlio.load(path) if path.suffix in (".yaml", ".yml") else None
            docs.append(Doc(rel=rel, data=data, raw=raw))
    return docs


def load_platform(authoring_root: Path, platform_id: str, _stack: tuple = ()) -> tuple[list[Doc], dict, dict]:
    """Return (docs, id_map_from_parent, platform_spec)."""
    if platform_id in _stack:
        raise AuthoringError(f"platform extends cycle: {_stack + (platform_id,)}")
    pdir = authoring_root / "platforms" / platform_id
    spec = yamlio.load(pdir / "platform.yaml")
    parent = spec.get("extends")
    if not parent:
        return _read_docs(pdir / "docs"), {}, spec
    parent_docs, _, _ = load_platform(authoring_root, parent, _stack + (platform_id,))
    rules = spec.get("rename") or []
    keep = spec.get("rename_exclude") or []   # e.g. ["00_sensor/*"]: shared, ids unchanged
    renamable = [d.id for d in parent_docs if d.id and not any(fnmatch.fnmatch(d.rel, g) for g in keep)]
    id_map = build_id_map(renamable, rules)
    removed = set(spec.get("remove_docs") or [])
    docs: list[Doc] = []
    for d in parent_docs:
        if d.id in removed:
            continue
        new_rel = "/".join(apply_rules(part, rules) for part in d.rel.split("/")) if d.id in id_map else d.rel
        if d.data is None:
            docs.append(Doc(rel=d.rel, raw=d.raw))
            continue
        data = rename_value(d.data, id_map)
        docs.append(Doc(rel=new_rel, data=data, raw=d.raw if data == d.data else None))
    for d in _read_docs(pdir / "docs"):   # additions / full replacements
        docs = [x for x in docs if not (x.id and x.id == d.id) and x.rel != d.rel]
        docs.append(d)
    _apply_doc_patches(docs, pdir / "patches", f"platform '{platform_id}'")
    return docs, id_map, spec


def _apply_doc_patches(docs: list[Doc], patch_dir: Path, owner: str) -> None:
    """``patches/<doc id>.yaml`` = deep-merge patch on that (already renamed) document."""
    if not patch_dir.exists():
        return
    by_id = {d.id: d for d in docs if d.id}
    for p in sorted(patch_dir.glob("*.yaml")):
        if p.stem not in by_id:
            raise AuthoringError(f"{owner} patch {p.name}: unknown doc id '{p.stem}'")
        doc = by_id[p.stem]
        doc.data = deep_merge(doc.data, yamlio.load(p) or {})
        doc.raw = None


def _load_root_project(jdir: Path, spec: dict) -> dict[str, Any]:
    scenarios = {}
    sdir = jdir / "scenarios"
    measured = {}
    if sdir.exists():
        for d in sorted(p for p in sdir.iterdir() if p.is_dir()):
            if (d / "scenario.yaml").exists():
                src = load_scenario_sources(d)
                scenarios[src["base"]["id"]] = src
            if (d / "sw_timing.measured.yaml").exists():
                measured[d.name] = yamlio.load(d / "sw_timing.measured.yaml") or {}
    return {"project": spec["document"], "docs": _read_docs(jdir / "docs"),
            "scenarios": scenarios, "measured": measured}


def load_project(authoring_root: Path, key: str, _stack: tuple = ()) -> Bundle:
    if key in _stack:
        raise AuthoringError(f"project extends cycle: {_stack + (key,)}")
    jdir = authoring_root / "projects" / key
    spec = yamlio.load(jdir / "project.yaml")
    platform_docs, platform_map, _ = load_platform(authoring_root, spec["platform"])
    parent_key = spec.get("extends")
    if not parent_key:
        root = _load_root_project(jdir, spec)
        return Bundle(spec["platform"], platform_docs, platform_map, key, root["project"], root["docs"],
                      root["scenarios"], root["measured"])

    parent = load_project(authoring_root, parent_key, _stack + (key,))
    # id map: platform rename (only if this platform directly extends the parent's) + project rules
    pspec = yamlio.load(authoring_root / "platforms" / spec["platform"] / "platform.yaml")
    if spec["platform"] == parent.platform_id:
        pmap = {}
    elif pspec.get("extends") == parent.platform_id:
        pmap = platform_map
    else:
        raise AuthoringError(
            f"project '{key}': platform '{spec['platform']}' must equal or directly extend "
            f"parent platform '{parent.platform_id}'")
    suffix = (spec.get("scenario_rename") or {}).get("suffix", "")
    ids = [parent.project["id"], *(d.id for d in parent.project_docs if d.id), *parent.scenarios]
    id_map = dict(pmap)
    id_map.update(build_id_map(ids, spec.get("rename") or []))
    for uc in parent.scenarios:
        if suffix and uc not in id_map:
            id_map[uc] = uc + suffix

    project = rename_value(parent.project, id_map)
    project = deep_merge(project, spec.get("document_patch") or {})
    docs = [Doc(rel="/".join(apply_rules(x, spec.get("rename") or []) for x in d.rel.split("/")),
                data=rename_value(d.data, id_map)) if d.data is not None else d
            for d in parent.project_docs]
    for d in _read_docs(jdir / "docs"):
        docs = [x for x in docs if not (x.id and x.id == d.id) and x.rel != d.rel]
        docs.append(d)
    _apply_doc_patches(docs, jdir / "patches", f"project '{key}'")

    include = (spec.get("scenarios") or {}).get("include", "*")
    exclude = set((spec.get("scenarios") or {}).get("exclude") or [])
    scenarios: dict[str, dict] = {}
    overlays: dict[str, dict] = {}
    measured: dict[str, dict] = {}
    origins: dict[str, str] = {}
    sdir = jdir / "scenarios"
    for uc, src in parent.scenarios.items():
        if uc in exclude or (include != "*" and uc not in include):
            continue
        new = {k: rename_value(copy.deepcopy(v), id_map) for k, v in src.items()}
        meta = new["base"].setdefault("metadata", {})
        meta.setdefault("canonical_usecase", uc)
        odir = sdir / uc
        if (odir / "overlay.yaml").exists():
            overlay = yamlio.load(odir / "overlay.yaml") or {}
            new = apply_overlay(new, rename_value(overlay, id_map))
            overlays[new["base"]["id"]] = overlay
        scenarios[new["base"]["id"]] = new
        origins[new["base"]["id"]] = uc
        if (odir / "sw_timing.measured.yaml").exists():
            measured[new["base"]["id"]] = yamlio.load(odir / "sw_timing.measured.yaml") or {}
    if sdir.exists():   # brand-new scenarios in the child project
        for sd in sorted(p for p in sdir.iterdir() if p.is_dir()):
            if (sd / "scenario.yaml").exists():
                src = load_scenario_sources(sd)
                scenarios[src["base"]["id"]] = src
                if (sd / "sw_timing.measured.yaml").exists():
                    measured[src["base"]["id"]] = yamlio.load(sd / "sw_timing.measured.yaml") or {}
    return Bundle(spec["platform"], platform_docs, platform_map, key, project, docs, scenarios, measured,
                  overlays, {"id_map": id_map}, origins)


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------

def compile_project(authoring_root: Path, key: str, out_dir: Path | None = None) -> dict[str, Any]:
    bundle = load_project(authoring_root, key)
    report: dict[str, Any] = {"project": key, "platform": bundle.platform_id, "scenarios": {},
                              "impact": {}, "measurements": {}}
    outputs: list[Doc] = []
    outputs.extend(bundle.platform_docs)
    outputs.extend(bundle.project_docs)
    outputs.append(Doc(rel=f"02_definition/{bundle.project['id']}.yaml", data=bundle.project))
    for uc, src in bundle.scenarios.items():
        doc = compile_usecase(src)
        overlay = bundle.overlays.get(uc) or {}
        impact = prune_or_report_missing_nodes(doc, prune=bool(overlay.get("prune_missing_nodes")))
        if impact:
            report["impact"][uc] = impact
        if uc in bundle.measured:
            report["measurements"][uc] = apply_sw_measurements(
                doc.get("variants") or [], bundle.measured[uc], src.get("sw_timing"),
                variant_parents(src["variants"]))
        report["scenarios"][uc] = {"variants": len(doc.get("variants") or [])}
        outputs.append(Doc(rel=f"02_definition/{uc}.yaml", data=doc))
    if out_dir is not None:
        write_docs(outputs, out_dir)
    report["documents"] = outputs
    return report


def write_docs(docs: list[Doc], out_dir: Path) -> None:
    seen: set[str] = set()
    for d in docs:
        if d.rel in seen:
            raise AuthoringError(f"duplicate output path {d.rel}")
        seen.add(d.rel)
        if not (out_dir / d.rel).resolve().is_relative_to(out_dir.resolve()):
            raise AuthoringError(f"output path escapes destination: {d.rel}")
    for d in docs:
        path = out_dir / d.rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if d.raw is not None:
            path.write_bytes(d.raw)
        else:
            yamlio.dump(path, d.data, header="GENERATED by scenario_db.authoring - edit authoring/ sources instead.")
