"""ORM metadata vs live DB drift, classified by runtime impact.

`alembic check` reports every difference, including cosmetic ones (index naming, server-default
rendering, migration-only indexes). This keeps only what breaks the ORM at runtime:
  FAIL  add_table / add_column       -> ORM selects a table/column the DB does not have (f405)
  WARN  modify_type / modify_nullable / remove_column (DB-only column; NOT NULL w/o default breaks inserts)
  INFO  index / default / DB-only table differences (performance or cosmetic)

Usage: uv run python scripts/check_schema_drift.py [--verbose]
Exit 1 when any FAIL is found.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from scenario_db.db.base import Base
import scenario_db.db.models  # noqa: F401  register all ORM models

ROOT = Path(__file__).resolve().parents[1]
FAIL_OPS = {"add_table", "add_column"}
WARN_OPS = {"modify_type", "modify_nullable", "remove_column"}


def _db_url() -> str:
    for key in ("SCENARIO_DB_DATABASE_URL", "DATABASE_URL"):
        if os.environ.get(key):
            return os.environ[key]
    env = ROOT / ".env"
    if env.exists():
        values = {}
        for line in env.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
        for key in ("SCENARIO_DB_DATABASE_URL", "DATABASE_URL"):
            if values.get(key):
                return values[key]
    sys.exit("DB URL not found (SCENARIO_DB_DATABASE_URL / DATABASE_URL / .env)")


def _flatten(diffs):
    for d in diffs:
        if isinstance(d, list):      # modify_* ops come grouped per column
            yield from d
        else:
            yield d


def _describe(op) -> str:
    kind = op[0]
    if kind in ("add_table", "remove_table"):
        return op[1].name
    if kind in ("add_column", "remove_column"):
        return f"{op[2]}.{op[3].name}"
    if kind.startswith("modify_"):
        return f"{op[2]}.{op[3]}  db={op[5]!r} -> orm={op[6]!r}"
    if kind in ("add_index", "remove_index"):
        idx = op[1]
        return f"{idx.table.name}.{idx.name}"
    return repr(op[1:])[:160]


def main() -> int:
    verbose = "--verbose" in sys.argv
    engine = create_engine(_db_url())
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        ops = list(_flatten(compare_metadata(ctx, Base.metadata)))
    buckets = {"FAIL": [], "WARN": [], "INFO": []}
    for op in ops:
        level = "FAIL" if op[0] in FAIL_OPS else "WARN" if op[0] in WARN_OPS else "INFO"
        buckets[level].append(f"{op[0]:<16} {_describe(op)}")
    for level in ("FAIL", "WARN") + (("INFO",) if verbose else ()):
        for line in buckets[level]:
            print(f"[{level}] {line}")
    print(f"\nFAIL={len(buckets['FAIL'])} WARN={len(buckets['WARN'])} INFO={len(buckets['INFO'])}"
          + ("" if verbose else "  (--verbose for INFO)"))
    return 1 if buckets["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
