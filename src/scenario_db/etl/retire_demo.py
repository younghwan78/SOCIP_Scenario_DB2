"""Retire the Exynos2500 demo from a runtime DB; fixture files stay intact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session

from scenario_db.db.base import Base, make_engine
import scenario_db.db.models  # noqa: F401
from scenario_db.db.models.capability import SimConfigProfile  # noqa: F401
from scenario_db.etl.validate_loaded import validate_loaded_db

SOC = "soc-exynos2500"
# Shared software/catalog definitions and immutable audit history are retained.
SCOPED = {
    "soc_platforms", "projects", "scenarios", "scenario_variants", "evidence",
    "sweep_jobs", "soc_dvfs_tables", "soc_cdgm_profiles", "sim_config_profiles",
    "issues", "waivers", "reviews", "gate_rules",
}


def strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(strings(v) for v in value.values()))
    if isinstance(value, (list, tuple)):
        return set().union(*(strings(v) for v in value))
    return set()


def plan_retirement(db: Session) -> dict[str, list[dict[str, Any]]]:
    tables = Base.metadata.tables
    rows = {name: [dict(r) for r in db.execute(select(tables[name])).mappings()]
            for name in SCOPED | {"ip_catalog"}}
    projects = {r["id"] for r in rows["projects"] if r["metadata"].get("soc_ref") == SOC}
    scenarios = {r["id"] for r in rows["scenarios"] if r["project_ref"] in projects}
    protected = {r["id"] for r in rows["projects"] if r["id"] not in projects}
    protected |= {r["id"] for r in rows["scenarios"] if r["id"] not in scenarios}
    refs = {SOC} | projects | scenarios
    plan: dict[str, list[dict[str, Any]]] = {name: [] for name in rows}
    changed = True
    while changed:
        changed = False
        for name in SCOPED:
            for row in rows[name]:
                # Variant IDs are only unique within their scenario.
                values = strings({k: v for k, v in row.items() if k != "id"})
                match = (row.get("id") == SOC if name == "soc_platforms" else bool(values & refs))
                if not match or row in plan[name]:
                    continue
                legacy_demo = (
                    name == "waivers"
                    and row.get("id") == "waiver-LLC-thrashing-UHD60-A0-20260417"
                    and row.get("issue_ref") == "iss-LLC-thrashing-0221"
                    and row.get("yaml_sha256") in {
                        "ecd7a3dd54b752f1b88adabc0be70feab9c970989bd4e0228f263876cf41db02",
                        "a796f5ded4b14a6e50e15f437efed62c0b11bd8d002f19b78617e15189d770a9",
                    }
                )  # Original demo before adaf960 renamed its scenario/silicon scope.
                if (values & protected or row.get("id") in protected) and not legacy_demo:
                    raise ValueError(f"Cross-project reference in {name}/{row.get('id')}; refusing retirement")
                plan[name].append(row)
                if name != "scenario_variants":
                    refs.add(row["id"])
                changed = True
    # Remove only exclusive demo IPs with no references from surviving rows.
    survivor_refs = set()
    for table in Base.metadata.sorted_tables:
        if table.name in {"ip_catalog", "sw_profiles", "sw_components"} or "audit" in table.name or table.name.startswith("write_"):
            continue
        for row in db.execute(select(table)).mappings():
            if dict(row) not in plan.get(table.name, []):
                survivor_refs |= strings(dict(row))
    plan["ip_catalog"] = [r for r in rows["ip_catalog"]
                          if r.get("compatible_soc") == [SOC] and r["id"] not in survivor_refs]
    return {name: items for name, items in plan.items() if items}


def retire_demo(db: Session, *, backup: Path | None = None) -> dict[str, int]:
    plan = plan_retirement(db)
    counts = {name: len(rows) for name, rows in sorted(plan.items())}
    if backup is None:
        return counts
    backup.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting an earlier recovery archive.
    with backup.open("x", encoding="utf-8") as stream:
        json.dump({"soc_ref": SOC, "tables": plan}, stream, default=str, indent=2)
    for table in reversed(Base.metadata.sorted_tables):
        for row in plan.get(table.name, []):
            db.execute(delete(table).where(and_(*(c == row[c.name] for c in table.primary_key))))
    report = validate_loaded_db(db)
    if not report.ok:
        raise ValueError("Retirement failed validation: " + "; ".join(report.errors))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path, help="New JSON archive path required with --apply")
    args = parser.parse_args()
    if args.apply and not args.backup:
        parser.error("--apply requires --backup")
    with Session(make_engine()) as db, db.begin():
        counts = retire_demo(db, backup=args.backup if args.apply else None)
    print(json.dumps({"applied": args.apply, "rows": counts}, indent=2))


if __name__ == "__main__":
    main()
