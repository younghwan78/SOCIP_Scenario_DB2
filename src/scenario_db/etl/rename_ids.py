"""Rename scenario / project / profile ids in a runtime DB in place.

Keeps runtime-only rows (predictions, exploration runs, reports, evidence) and
rewrites every reference to the renamed ids: primary keys, foreign keys, plain
text columns and exact string values (or dict keys) inside JSON columns.

    python -m scenario_db.etl.rename_ids --map authoring/id-renames.yaml            # dry run
    python -m scenario_db.etl.rename_ids --map authoring/id-renames.yaml --apply \\
        --backup output/etl/rename-backup.json

Rows whose new primary key already exists (fixture already reloaded with the new
ids) are dropped in favour of the existing row. Idempotent: a second run finds
nothing to change. FK triggers are disabled for the transaction
(``session_replication_role = replica``), which needs a superuser role — the
docker-compose ``scenario_user`` is one.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import and_, delete, select, text, update
from sqlalchemy.orm import Session

import scenario_db.db.models  # noqa: F401
from scenario_db.db.base import Base, make_engine
from scenario_db.etl.validate_loaded import validate_loaded_db


def load_map(path: Path) -> dict[str, str]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mapping = {str(k): str(v) for k, v in (doc.get("renames") or {}).items() if k != v}
    loops = set(mapping) & set(mapping.values())
    if loops:
        raise ValueError(f"rename map is not one-step (old ids reused as new ids): {sorted(loops)}")
    return mapping


def rewrite(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [rewrite(v, mapping) for v in value]
    if isinstance(value, dict):
        return {mapping.get(k, k) if isinstance(k, str) else k: rewrite(v, mapping) for k, v in value.items()}
    return value


def plan_renames(db: Session, mapping: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """Per table: [{pk: old pk values, changes: {column: new value}, merge: bool}]."""
    plan: dict[str, list[dict[str, Any]]] = {}
    for table in Base.metadata.sorted_tables:
        pk_cols = [c.name for c in table.primary_key]
        rows = [dict(r) for r in db.execute(select(table)).mappings()]
        existing = {tuple(r[c] for c in pk_cols) for r in rows}
        entries = []
        for row in rows:
            changes = {}
            for col, val in row.items():
                new = rewrite(val, mapping)
                if new != val:
                    changes[col] = new
            if not changes:
                continue
            old_pk = tuple(row[c] for c in pk_cols)
            new_pk = tuple(changes.get(c, row[c]) for c in pk_cols)
            entries.append({"pk": dict(zip(pk_cols, old_pk)), "changes": changes,
                            "merge": new_pk != old_pk and new_pk in existing, "row": row})
        if entries:
            plan[table.name] = entries
    return plan


def apply_renames(db: Session, plan: dict[str, list[dict[str, Any]]]) -> None:
    db.execute(text("SET LOCAL session_replication_role = replica"))
    tables = Base.metadata.tables
    for name, entries in plan.items():
        table = tables[name]
        for e in entries:
            where = and_(*(table.c[k] == v for k, v in e["pk"].items()))
            if e["merge"]:
                db.execute(delete(table).where(where))
            else:
                db.execute(update(table).where(where).values(**e["changes"]))
    db.execute(text("SET LOCAL session_replication_role = origin"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--map", type=Path, default=Path("authoring/id-renames.yaml"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path, help="New JSON archive of the affected rows (required with --apply)")
    args = parser.parse_args()
    if args.apply and not args.backup:
        parser.error("--apply requires --backup")
    mapping = load_map(args.map)
    with Session(make_engine()) as db, db.begin():
        plan = plan_renames(db, mapping)
        summary = {name: {"renamed": sum(not e["merge"] for e in rows), "merged_into_existing": sum(e["merge"] for e in rows)}
                   for name, rows in plan.items()}
        if args.apply and plan:
            args.backup.parent.mkdir(parents=True, exist_ok=True)
            with args.backup.open("x", encoding="utf-8") as stream:
                json.dump({"map": mapping, "rows": {n: [e["row"] for e in rows] for n, rows in plan.items()}},
                          stream, default=str, indent=2, ensure_ascii=False)
            apply_renames(db, plan)
            report = validate_loaded_db(db)
            if not report.ok:
                raise ValueError("rename failed validation: " + "; ".join(report.errors[:10]))
    print(json.dumps({"applied": bool(args.apply and plan), "tables": summary}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
