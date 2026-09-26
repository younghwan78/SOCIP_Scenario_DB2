"""Rename scenario / project / profile ids in a runtime DB in place.

Keeps runtime-only rows (predictions, exploration runs, reports, evidence) and
rewrites every reference to the renamed ids: primary keys, foreign keys, plain
text columns and exact string values (or dict keys) inside JSON columns.

    python -m scenario_db.etl.rename_ids --map authoring/id-renames.yaml            # dry run
    python -m scenario_db.etl.rename_ids --map authoring/id-renames.yaml --apply \\
        --backup output/etl/rename-backup.json

Rows whose new primary key already exists (fixture already reloaded with the new
ids, or two scenarios merged into one) are dropped in favour of the existing row.
Run the fixture ETL (--strict) afterwards; it is the validation gate. Idempotent: a second run finds
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
from scenario_db.etl.reference_validation import validate_foreign_keys


def load_map(path: Path) -> dict[str, str]:
    """old -> final id. Chains (a->b, b->c) collapse to a->c, b->c; cycles are rejected."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = {str(k): str(v) for k, v in (doc.get("renames") or {}).items() if k != v}
    out: dict[str, str] = {}
    for key in raw:
        seen = [key]
        cur = raw[key]
        while cur in raw:
            if cur in seen:
                raise ValueError(f"rename map has a cycle: {' -> '.join(seen + [cur])}")
            seen.append(cur)
            cur = raw[cur]
        out[key] = cur
    return out


# Values under these keys are cross-project join keys, not id references. An old scenario id
# can coincide with one (e.g. uc-game-play), so they are never rewritten.
PROTECTED_KEYS = frozenset({"canonical_usecase"})
# ETL skips a scenario whose stored source hash matches the fixture, so a scenario row edited here
# gets a marker hash (column is NOT NULL) and is reloaded (and re-validated) from the fixture on the
# next ETL. Other tables keep their hash: evidence/sensor hashes are provenance for runtime rows.
HASH_COLUMN = "yaml_sha256"
STALE_HASH = "stale:rename_ids"


def rewrite(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [rewrite(v, mapping) for v in value]
    if isinstance(value, dict):
        return {mapping.get(k, k) if isinstance(k, str) else k: v if k in PROTECTED_KEYS else rewrite(v, mapping)
                for k, v in value.items()}
    return value


def _canonical_corrupted(row: dict[str, Any], targets: set[str]) -> bool:
    """canonical_usecase rewritten to a scenario id by an earlier rename (before PROTECTED_KEYS)."""
    meta = row.get("metadata")
    return isinstance(meta, dict) and meta.get("canonical_usecase") in targets


def plan_renames(db: Session, mapping: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """Per table: [{pk: old pk values, changes: {column: new value}, merge: bool}]."""
    plan: dict[str, list[dict[str, Any]]] = {}
    targets = set(mapping.values())
    for table in Base.metadata.sorted_tables:
        pk_cols = [c.name for c in table.primary_key]
        rows = [dict(r) for r in db.execute(select(table)).mappings()]
        existing = {tuple(r[c] for c in pk_cols) for r in rows}
        entries = []
        for row in rows:
            changes = {}
            for col, val in row.items():
                if table.c[col].computed is not None:
                    continue
                new = rewrite(val, mapping)
                if new != val:
                    changes[col] = new
            if table.name == "scenarios" and row.get(HASH_COLUMN) != STALE_HASH and _canonical_corrupted(row, targets):
                changes.setdefault("metadata", row["metadata"])   # repaired by the next ETL reload
            if not changes:
                continue
            if table.name == "scenarios":
                changes[HASH_COLUMN] = STALE_HASH
            old_pk = tuple(row[c] for c in pk_cols)
            new_pk = tuple(changes.get(c, row[c]) for c in pk_cols)
            entries.append({"pk": dict(zip(pk_cols, old_pk)), "changes": changes,
                            "merge": new_pk != old_pk and new_pk in existing, "row": row})
        destinations = [tuple(e["changes"].get(c, e["pk"][c]) for c in pk_cols)
                        for e in entries if not e["merge"]]
        if len(destinations) != len(set(destinations)):
            raise ValueError(f"ambiguous rename collision in {table.name}; resolve duplicate targets first")
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
    validate_foreign_keys(db)


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
            # Merged scenarios are only consistent again after the fixture reload (ETL --strict
            # validates then), so post-rename findings are reported, not fatal.
            report = validate_loaded_db(db)
            summary["post_rename_validation"] = {"ok": report.ok, "errors": report.errors[:10]}
    print(json.dumps({"applied": bool(args.apply and plan), "tables": summary}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
