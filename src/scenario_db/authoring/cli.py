"""CLI: python -m scenario_db.authoring <command>

  decompile <fixture_dir> --platform P --project K [--root authoring]
  compile   <project key>  --out DIR [--root authoring]
  check     <project key>  --against <fixture_dir> [--root authoring]
  worksheet <project key>  [--root authoring]   write sw_timing.measured.yaml slots
  sync      <project key>  --fixture DIR --to fixture|authoring [--prune] [--dry-run]

Transition (both directions supported):
  fixture edited by generators  -> sync --to authoring  (root projects only; keeps hand-authored
                                   knobs.yaml / overlay.yaml / measured files and reviewed bindings)
  authoring edited              -> sync --to fixture    (writes only semantically changed files)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scenario_db.authoring import yamlio
from scenario_db.authoring.patch import diff_paths
from scenario_db.authoring.scenario import AuthoringError
from scenario_db.authoring.tree import compile_project, decompile_fixture, load_project, write_docs
from scenario_db.authoring.validate import validate_documents

AUTHORED_TOPS = ("00_hw", "00_sensor", "01_sw", "02_definition")


def _summary(report: dict, validation: dict) -> dict:
    return {
        "project": report["project"],
        "platform": report["platform"],
        "documents": len(report["documents"]),
        "scenarios": report["scenarios"],
        "impact": report["impact"],
        "measurements": report["measurements"],
        "errors": validation["errors"],
        "warnings": validation["warnings"],
    }


def check_against(root: Path, key: str, fixture: Path) -> list[str]:
    report = compile_project(root, key)
    compiled = {d.rel: d for d in report["documents"]}
    problems: list[str] = []
    for path in sorted(fixture.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(fixture).as_posix()
        if rel.split("/")[0] not in AUTHORED_TOPS:
            continue
        if rel not in compiled:
            problems.append(f"missing in compiled output: {rel}")
            continue
        d = compiled.pop(rel)
        if path.suffix in (".yaml", ".yml"):
            diffs = diff_paths(yamlio.load(path), d.data)
            problems.extend(f"{rel}: {x}" for x in diffs[:20])
        elif d.raw != path.read_bytes():
            problems.append(f"{rel}: content differs")
    problems.extend(f"extra in compiled output: {rel}" for rel in compiled)
    return problems


def sync_to_fixture(root: Path, key: str, fixture: Path, *, prune: bool = False,
                    dry_run: bool = False) -> dict[str, list[str]]:
    report = compile_project(root, key)
    validation = validate_documents(report["documents"])
    if validation["errors"]:
        raise AuthoringError("compiled documents invalid: " + "; ".join(validation["errors"][:10]))
    result: dict[str, list[str]] = {"added": [], "updated": [], "unchanged": [], "removed": []}
    changed = []
    produced = set()
    for d in report["documents"]:
        produced.add(d.rel)
        target = fixture / d.rel
        if not target.exists():
            result["added"].append(d.rel)
            changed.append(d)
            continue
        if d.raw is not None:
            same = target.read_bytes() == d.raw
        elif target.suffix in (".yaml", ".yml"):
            same = not diff_paths(yamlio.load(target), d.data)
        else:
            same = False
        (result["unchanged"] if same else result["updated"]).append(d.rel)
        if not same:
            changed.append(d)
    if prune:
        for path in sorted(fixture.rglob("*.yaml")):
            rel = path.relative_to(fixture).as_posix()
            if rel.split("/")[0] in AUTHORED_TOPS and rel not in produced:
                result["removed"].append(rel)
                if not dry_run:
                    path.unlink()
    if not dry_run:
        write_docs(changed, fixture)
    return result


def write_worksheet(root: Path, key: str) -> list[Path]:
    """Create/refresh sw_timing.measured.yaml with one pending slot per task group."""
    bundle = load_project(root, key)
    written = []
    for uc, src in bundle.scenarios.items():
        tasks = (src.get("sw_timing") or {}).get("tasks") or {}
        if not tasks:
            continue
        parent_uc = bundle.origins.get(uc, uc)   # authoring dir = parent scenario id
        target = root / "projects" / key / "scenarios" / parent_uc / "sw_timing.measured.yaml"
        if target.exists():
            continue
        entries = []
        for task, spec in tasks.items():
            for g in spec.get("groups") or []:
                entries.append({
                    "task": task,
                    "group": g["id"],
                    "baseline": {k: g["timing"].get(k) for k in ("min_ms", "mean_ms", "max_ms")
                                 if k in g["timing"]},
                    "timing": None,
                })
        yamlio.dump(target, {"kind": "authoring.sw_timing_measured", "scenario": uc, "entries": entries},
                    header="Measured SW timing slots. Fill `timing` (e.g. from semantic Perfetto) and keep\n"
                           "`baseline` as reference. `timing: null` = pending (compiler keeps baseline).\n"
                           "`group` = group id in the inherited sw_timing.yaml. Narrow further with\n"
                           "`when: {resolution: UHD}` or an explicit `variants` list; later entries win.\n"
                           "Example timing: {min_ms: 0.2, mean_ms: 0.4, max_ms: 0.7, value_source: measured,\n"
                           "                 source_note: 'perfetto <trace id>'}")
        written.append(target)
    return written


def show_variant(root: Path, key: str, scenario: str, variant: str) -> str:
    """Compiled (fully resolved) variant + its `extends` children in the source files."""
    import yaml

    from scenario_db.authoring.tree import load_project
    report = compile_project(root, key)
    doc = next((d.data for d in report["documents"] if isinstance(d.data, dict) and d.data.get("id") == scenario), None)
    if doc is None:
        raise AuthoringError(f"scenario '{scenario}' not in project '{key}'")
    v = next((x for x in doc.get("variants") or [] if x["id"] == variant), None)
    if v is None:
        raise AuthoringError(f"variant '{variant}' not in '{scenario}': {[x['id'] for x in doc['variants']]}")
    entries = load_project(root, key).scenarios[scenario]["variants"]
    parents = {e["id"]: e.get("extends") for e in entries}

    def descendants(vid: str) -> list[str]:
        kids = [k for k, p in parents.items() if p == vid]
        return kids + [d for k in kids for d in descendants(k)]
    chain, cur = [], parents.get(variant)
    while cur:
        chain.append(cur)
        cur = parents.get(cur)
    head = (f"# {scenario} / {variant}\n# extends: {' <- '.join(chain) or '(root entry)'}\n"
            f"# editing its entry also changes: {', '.join(descendants(variant)) or '(none)'}\n")
    return head + yaml.safe_dump(v, sort_keys=False, allow_unicode=True, width=120)


def _git_head(root: Path) -> str | None:
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True,
                              text=True, check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scenario_db.authoring")
    ap.add_argument("--root", type=Path, default=Path("authoring"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decompile")
    d.add_argument("fixture", type=Path)
    d.add_argument("--platform", required=True)
    d.add_argument("--project", required=True)
    c = sub.add_parser("compile")
    c.add_argument("project")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--report-json", type=Path)
    k = sub.add_parser("check")
    k.add_argument("project")
    k.add_argument("--against", type=Path, required=True)
    e = sub.add_parser("eject", help="write every inherited doc/scenario of a derived project as editable files")
    e.add_argument("project")
    e.add_argument("--commit", help="source commit to record (default: git rev-parse HEAD)")
    pd = sub.add_parser("parent-diff", help="parent changes since an eject")
    pd.add_argument("project")
    pd.add_argument("--limit", type=int, default=20)
    pd.add_argument("--accept", action="store_true", help="mark the current parent state as reviewed")
    sh = sub.add_parser("show", help="print one compiled variant and the variants that extend it")
    sh.add_argument("project")
    sh.add_argument("scenario")
    sh.add_argument("variant")
    w = sub.add_parser("worksheet")
    w.add_argument("project")
    y = sub.add_parser("sync")
    y.add_argument("project")
    y.add_argument("--fixture", type=Path, required=True)
    y.add_argument("--to", choices=("fixture", "authoring"), required=True)
    y.add_argument("--prune", action="store_true", help="--to fixture: delete 00-02 YAML not produced")
    y.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "decompile":
            stats = decompile_fixture(args.fixture, args.root, args.platform, args.project)
            print(json.dumps(stats, indent=2, ensure_ascii=False))
            return 0
        if args.cmd == "compile":
            report = compile_project(args.root, args.project)
            summary = _summary(report, validate_documents(report["documents"]))
            if not summary["errors"]:
                write_docs(report["documents"], args.out)
            text = json.dumps(summary, indent=2, ensure_ascii=False)
            if args.report_json:
                args.report_json.parent.mkdir(parents=True, exist_ok=True)
                args.report_json.write_text(text, encoding="utf-8")
            print(text)
            return 1 if summary["errors"] else 0
        if args.cmd == "check":
            problems = check_against(args.root, args.project, args.against)
            for p in problems[:200]:
                print(p)
            print(f"{len(problems)} difference(s)")
            return 1 if problems else 0
        if args.cmd == "sync":
            if args.to == "fixture":
                res = sync_to_fixture(args.root, args.project, args.fixture, prune=args.prune,
                                      dry_run=args.dry_run)
                print(json.dumps({k: (v if k != "unchanged" else len(v)) for k, v in res.items()},
                                 indent=2, ensure_ascii=False))
                return 0
            spec = yamlio.load(args.root / "projects" / args.project / "project.yaml")
            if spec.get("extends"):
                raise AuthoringError(f"project '{args.project}' extends '{spec['extends']}': only root "
                                     "projects can be decompiled; edit its overlay/patch files instead")
            if args.dry_run:
                problems = check_against(args.root, args.project, args.fixture)
                print("\n".join(problems[:200]) + f"\n{len(problems)} difference(s)")
                return 0
            stats = decompile_fixture(args.fixture, args.root, spec["platform"], args.project)
            print(json.dumps({"platform_docs": stats["platform_docs"], "project_docs": stats["project_docs"],
                              "scenarios": len(stats["scenarios"]), "not_authored": len(stats["skipped"]),
                              "stale_scenarios": stats["stale_scenarios"]}, indent=2, ensure_ascii=False))
            return 0
        if args.cmd == "eject":
            from scenario_db.authoring.eject import eject_project
            commit = args.commit or _git_head(args.root)
            print(json.dumps(eject_project(args.root, args.project, commit=commit), indent=2, ensure_ascii=False))
            return 0
        if args.cmd == "parent-diff":
            from scenario_db.authoring.eject import accept_parent, parent_diff
            if args.accept:
                print(f"accepted: {accept_parent(args.root, args.project)} parent documents re-baselined")
                return 0
            res = parent_diff(args.root, args.project, limit=args.limit)
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return 0
        if args.cmd == "show":
            print(show_variant(args.root, args.project, args.scenario, args.variant))
            return 0
        if args.cmd == "worksheet":
            for written in write_worksheet(args.root, args.project):
                print(written)
            return 0
    except AuthoringError as exc:
        print(f"authoring error: {exc}", file=sys.stderr)
        return 2
    return 0
