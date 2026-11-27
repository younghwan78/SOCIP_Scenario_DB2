"""Change gate: a branch against its base on the E2600 fixed cases and every E2700 variant, without a database.

Run from the repository root:

    uv run python scripts/check_change_gate.py run --base main

``run`` checks the base out into a temporary worktree, dumps both trees with this interpreter (each tree's own
``src`` / ``scripts`` / fixtures first on ``sys.path``), compares them and checks the E2700 documents
(``authoring check sm-s957b``). The comparison is split into three groups:

* **E2600 results** - ``check_engine_equivalence`` fixed cases, outside the input hash: expected for an intended
  change; reported (``--strict`` fails on it).
* **E2600 input hash** - ``input_hash`` / ``input_sections`` / ``_manifest_blobs``: a changed hash makes a
  registered prediction of that case stale; reported (``--strict`` fails on it).
* **E2700** - Timing Budget reports and DMA breakdowns of every E2700 variant, and the documents: an E2600 change
  must never move them, so any difference fails.

``dump --root DIR --out OUT`` and ``compare --a A --b B`` are the two halves, for a manual run.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

HERE = Path(__file__).resolve()
REPO = HERE.parents[1]
E2700_FIXTURE = "db_Exynos2700_SM-S957B"
E2700_PROJECT = "sm-s957b"
HASH_KEYS = frozenset({"input_hash", "input_sections", "_manifest_blobs"})


# ---------------------------------------------------------------- dump (runs inside one tree)

def _use_tree(root: Path) -> None:
    """Make ``root``'s sources, scripts and tests win over the installed package (run before any import)."""
    for entry in (root / "scripts", root / "src", root):
        sys.path.insert(0, str(entry))
    os.chdir(root)


def _e2700_cases(root: Path) -> list[tuple[str, str]]:
    from scenario_db.yaml_loader import safe_load

    cases = []
    for path in sorted((root / E2700_FIXTURE / "02_definition").glob("uc-*.yaml")):
        doc = safe_load(path.read_text(encoding="utf-8"))
        cases += [(doc["id"], v["id"]) for v in doc.get("variants") or []]
    return cases


def _dump_e2700(root: Path, out: Path) -> int:
    from check_engine_equivalence import canonical_json
    from scenario_db.sim.adapter import build_simulation_inputs
    from scenario_db.sim.models import DVFSTable
    from scenario_db.sim.runner import run_simulation
    from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
    from scenario_db.yaml_loader import safe_load
    from tests.unit.sim.test_adapter_runner import _fixture_graph

    dvfs = safe_load((root / E2700_FIXTURE / "00_hw" / "dvfs-exynos2700-sample-v0.yaml").read_text(encoding="utf-8"))
    tables = {k: DVFSTable.model_validate(v) for k, v in dvfs["domains"].items()}
    out.mkdir(parents=True, exist_ok=True)
    cases = _e2700_cases(root)
    for scenario_id, variant_id in cases:
        result: dict[str, Any] = {"scenario_id": scenario_id}
        try:
            result["timing_budget"] = analyze_timing_budget(
                _fixture_graph(E2700_FIXTURE, scenario_id, variant_id),
                TimingBudgetOptions(throughput_model="pipelined"), dvfs_tables=tables)
        except Exception as exc:   # an error is a result too: it must not change either
            result["timing_budget"] = f"{type(exc).__name__}: {exc}"
        try:
            run = run_simulation(build_simulation_inputs(_fixture_graph(E2700_FIXTURE, scenario_id, variant_id), None))
            result["dma"] = [[x.node_id, x.port, x.bw_mbs, x.bw_power_mw] for x in run.dma_breakdown]
        except Exception as exc:
            result["dma"] = f"{type(exc).__name__}: {exc}"
        (out / f"{variant_id}.json").write_bytes(canonical_json(result).encode("utf-8"))
    print(f"E2700: dumped {len(cases)} variants", flush=True)
    return len(cases)


def dump(root: Path, out: Path) -> int:
    _use_tree(root)
    import scenario_db
    from check_engine_equivalence import dump as dump_e2600

    source = Path(scenario_db.__file__).resolve()
    if root.resolve() not in source.parents:   # an import hook of the installed package would win over sys.path
        raise SystemExit(f"scenario_db resolves to {source}, not to {root}/src")
    dump_e2600(out / "e2600", runs=1)
    _dump_e2700(root, out / "e2700")
    return 0


# ---------------------------------------------------------------- compare

def _differing(a: Any, b: Any, path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Paths whose values differ (a dict key missing on one side counts as a difference)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[tuple[str, ...]] = []
        for key in sorted(a.keys() | b.keys()):
            if key not in a or key not in b:
                out.append((*path, str(key)))
            else:
                out += _differing(a[key], b[key], (*path, str(key)))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [path] if any(_differing(x, y) for x, y in zip(a, b)) else []
    return [] if a == b and type(a) is type(b) else [path]   # 1 != 1.0: the type is part of the result


def _files(folder: Path) -> dict[str, Path]:
    return {p.name: p for p in folder.glob("*.json")} if folder.is_dir() else {}


def summarize(a: Path, b: Path) -> dict[str, dict[str, list[str]]]:
    """``{group: {case: [first differing paths]}}`` for groups e2600_results, e2600_input_hash, e2700."""
    groups: dict[str, dict[str, list[str]]] = {"e2600_results": {}, "e2600_input_hash": {}, "e2700": {}}
    for sub, split in (("e2600", True), ("e2700", False)):
        left, right = _files(a / sub), _files(b / sub)
        if not left and not right:
            raise ValueError(f"no {sub} dump in {a} / {b}")
        for name in sorted(left.keys() | right.keys()):
            case = name.removesuffix(".json")
            if name not in left or name not in right:
                key = "e2600_results" if split else "e2700"
                groups[key][case] = [f"missing from {'a' if name not in left else 'b'}"]
                continue
            if left[name].read_bytes() == right[name].read_bytes():
                continue
            paths = _differing(json.loads(left[name].read_bytes()), json.loads(right[name].read_bytes()))
            if not paths:            # same values, different encoding
                paths = [("<encoding>",)]
            if not split:
                groups["e2700"][case] = [".".join(p) for p in paths[:5]]
                continue
            hashed = [p for p in paths if p and p[0] in HASH_KEYS]
            rest = [p for p in paths if not (p and p[0] in HASH_KEYS)]
            if hashed:
                groups["e2600_input_hash"][case] = sorted({p[0] for p in hashed})
            if rest:
                groups["e2600_results"][case] = [".".join(p) for p in rest[:5]]
    return groups


def report(groups: dict[str, dict[str, list[str]]], *, strict: bool, docs_problems: list[str] | None = None) -> int:
    titles = {"e2600_results": "E2600 results (intended changes only)",
              "e2600_input_hash": "E2600 input hash (registered predictions of these cases go stale)",
              "e2700": "E2700 (must not change)"}
    for key, title in titles.items():
        cases = groups[key]
        print(f"{title}: {len(cases)} case(s) differ")
        for case, paths in cases.items():
            print(f"  {case}: {', '.join(paths)}")
    if docs_problems is not None:
        print(f"E2700 documents ({E2700_PROJECT} vs {E2700_FIXTURE}): {len(docs_problems)} difference(s)")
        for line in docs_problems[:20]:
            print(f"  {line}")
    failed = bool(groups["e2700"] or docs_problems)
    if strict:
        failed = failed or bool(groups["e2600_results"] or groups["e2600_input_hash"])
    print("GATE FAIL" if failed else "GATE OK")
    return int(failed)


# ---------------------------------------------------------------- run (base vs this tree)

def _dump_in_subprocess(root: Path, out: Path) -> None:
    subprocess.run([sys.executable, str(HERE), "dump", "--root", str(root), "--out", str(out)], check=True)


def _docs_problems(root: Path) -> list[str]:
    proc = subprocess.run([sys.executable, "-m", "scenario_db.authoring", "check", E2700_PROJECT,
                           "--against", E2700_FIXTURE], cwd=root, capture_output=True, text=True,
                          encoding="utf-8", env={**os.environ, "PYTHONPATH": str(root / "src")})
    lines = [x for x in proc.stdout.splitlines() if x.strip()]
    if proc.returncode not in (0, 1) or not lines or not lines[-1].endswith("difference(s)"):
        return [f"authoring check failed to run (exit {proc.returncode}): {proc.stderr.strip()[-300:]}"]
    return lines[:-1]


def run(base: str, *, strict: bool, keep: Path | None) -> int:
    work = Path(tempfile.mkdtemp(prefix="change-gate-")) if keep is None else keep
    tree = work / "base-tree"
    subprocess.run(["git", "worktree", "add", "--detach", "-q", str(tree), base], cwd=REPO, check=True)
    try:
        lock_changed = subprocess.run(["git", "diff", "--quiet", base, "--", "uv.lock"], cwd=REPO).returncode != 0
        if lock_changed:
            print("note: uv.lock differs from the base; both trees run with this environment")
        _dump_in_subprocess(tree, work / "base")
        _dump_in_subprocess(REPO, work / "head")
        groups = summarize(work / "base", work / "head")
        return report(groups, strict=strict, docs_problems=_docs_problems(REPO))
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=REPO, check=False)
        if keep is None:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"dumps kept in {work}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modes = parser.add_subparsers(dest="mode", required=True)
    r = modes.add_parser("run", help="dump the base and this tree, compare, check the E2700 documents")
    r.add_argument("--base", default="main")
    r.add_argument("--strict", action="store_true", help="fail on E2600 differences too")
    r.add_argument("--keep", type=Path, help="keep the dumps in this folder")
    d = modes.add_parser("dump", help="dump one tree (E2600 fixed cases, every E2700 variant)")
    d.add_argument("--root", type=Path, default=REPO)
    d.add_argument("--out", type=Path, required=True)
    c = modes.add_parser("compare", help="compare two dumps by group")
    c.add_argument("--a", type=Path, required=True)
    c.add_argument("--b", type=Path, required=True)
    c.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    if args.mode == "dump":
        return dump(args.root.resolve(), args.out.resolve())
    if args.mode == "compare":
        return report(summarize(args.a, args.b), strict=args.strict)
    return run(args.base, strict=args.strict, keep=args.keep.resolve() if args.keep else None)


if __name__ == "__main__":
    raise SystemExit(main())
