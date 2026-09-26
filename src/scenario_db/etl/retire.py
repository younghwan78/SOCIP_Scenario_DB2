"""Retire projects / SoCs / scenarios / variants from a runtime DB (fixtures untouched).

Driven by ``authoring/retired.yaml`` so every DB matches the authoring scope:

    python -m scenario_db.etl.retire                                   # dry run
    python -m scenario_db.etl.retire --apply --backup output/etl/retire-backup.json

Spec (list of entries, applied cumulatively; idempotent)::

    retire:
    - date: 2026-09-27
      reason: ...
      projects: [proj-sm-s957b]          # project + its scenarios, variants, evidence,
                                         # predictions, runs, reports, sim config profiles
      socs: [soc-exynos2700]             # SoC + DVFS / CDGM tables of that SoC
      ips: ["ip-*-s5e9975"]              # glob on ip_catalog.id
      scenarios: [uc-vid-youtube-e2600]  # scenario + everything referencing it
      variants:                          # single variants (rows keyed by scenario+variant)
        uc-cam-recording-e2600: [cam-rec-r1-fhd30-sdr]

Multi-variant history (arch exploration runs) is kept unless its project is retired.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import and_, delete, select, text
from sqlalchemy.orm import Session

import scenario_db.db.models  # noqa: F401
from scenario_db.db.base import Base, make_engine
from scenario_db.etl.validate_loaded import validate_loaded_db
from scenario_db.etl.reference_validation import validate_foreign_keys

PROJECT_COLS = ("project_ref", "project_id", "source_project_ref")
SCENARIO_COLS = ("scenario_ref", "scenario_id")
VARIANT_COLS = ("variant_ref",)
SOC_COLS = ("soc_ref", "target_soc_ref")


def load_spec(path: Path) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    spec: dict[str, Any] = {"projects": set(), "socs": set(), "ips": [], "scenarios": set(), "variants": set()}
    for entry in doc.get("retire") or []:
        spec["projects"] |= set(entry.get("projects") or [])
        spec["socs"] |= set(entry.get("socs") or [])
        spec["ips"] += list(entry.get("ips") or [])
        spec["scenarios"] |= set(entry.get("scenarios") or [])
        for sc, vids in (entry.get("variants") or {}).items():
            spec["variants"] |= {(sc, v) for v in vids or []}
    return spec


def plan_retirement(db: Session, spec: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    tables = Base.metadata.tables
    rows = {name: [dict(r) for r in db.execute(select(t)).mappings()] for name, t in tables.items()}
    projects = set(spec["projects"])
    scenarios = set(spec["scenarios"]) | {r["id"] for r in rows.get("scenarios", []) if r.get("project_ref") in projects}
    socs = set(spec["socs"])
    variants = set(spec["variants"])
    plan: dict[str, list[dict[str, Any]]] = {}

    def hit(name: str, r: dict[str, Any]) -> bool:
        if name == "projects":
            return r["id"] in projects
        if name == "soc_platforms":
            return r["id"] in socs
        if name == "scenarios":
            return r["id"] in scenarios
        if name == "ip_catalog":
            return any(fnmatch.fnmatch(r["id"], g) for g in spec["ips"])
        if name == "scenario_variants":
            return r["scenario_id"] in scenarios or (r["scenario_id"], r["id"]) in variants
        if any(r.get(c) in projects for c in PROJECT_COLS if c in r):
            return True
        if any(r.get(c) in socs for c in SOC_COLS if c in r):
            return True
        sc = next((r.get(c) for c in SCENARIO_COLS if c in r), None)
        if sc in scenarios:
            return True
        vid = next((r.get(c) for c in VARIANT_COLS if c in r), None)
        return sc is not None and (sc, vid) in variants

    for name, table_rows in rows.items():
        matched = [r for r in table_rows if hit(name, r)]
        if matched:
            plan[name] = matched
    return plan


def apply_plan(db: Session, plan: dict[str, list[dict[str, Any]]]) -> None:
    db.execute(text("SET LOCAL session_replication_role = replica"))
    for table in reversed(Base.metadata.sorted_tables):
        for row in plan.get(table.name, []):
            db.execute(delete(table).where(and_(*(c == row[c.name] for c in table.primary_key))))
    db.execute(text("SET LOCAL session_replication_role = origin"))
    validate_foreign_keys(db)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spec", type=Path, default=Path("authoring/retired.yaml"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path, help="New JSON archive of deleted rows (required with --apply)")
    args = parser.parse_args()
    if args.apply and not args.backup:
        parser.error("--apply requires --backup")
    spec = load_spec(args.spec)
    with Session(make_engine()) as db, db.begin():
        plan = plan_retirement(db, spec)
        if args.apply and plan:
            args.backup.parent.mkdir(parents=True, exist_ok=True)
            with args.backup.open("x", encoding="utf-8") as stream:
                json.dump({"spec": args.spec.as_posix(), "tables": plan}, stream, default=str, indent=2, ensure_ascii=False)
            apply_plan(db, plan)
            report = validate_loaded_db(db)
            if not report.ok:
                raise ValueError("retirement failed validation: " + "; ".join(report.errors[:10]))
    print(json.dumps({"applied": bool(args.apply and plan), "rows": {k: len(v) for k, v in sorted(plan.items())}}, indent=2))


if __name__ == "__main__":
    main()
