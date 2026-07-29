from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scenario_db.config import get_settings
from scenario_db.db.models.evidence import Evidence
from scenario_db.reporting.reconciliation import reconcile_artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile simulation artifact metadata with the local report store.",
    )
    parser.add_argument(
        "--apply-stale-staging",
        action="store_true",
        help="Remove stale exporter staging directories; all other findings remain read-only.",
    )
    parser.add_argument("--stale-after-seconds", type=int, default=3_600)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.stale_after_seconds < 0:
        raise SystemExit("--stale-after-seconds must be non-negative")
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with Session(engine) as db:
            rows = (
                db.query(Evidence)
                .filter(Evidence.kind == "evidence.simulation")
                .all()
            )
            records: list[dict[str, Any]] = []
            for row in rows:
                raw_artifacts: Any = row.artifacts
                records.extend(
                    dict(item)
                    for item in (raw_artifacts or [])
                    if isinstance(item, dict)
                )
        findings = reconcile_artifacts(
            settings.report_dir,
            records,
            stale_after_seconds=args.stale_after_seconds,
            apply_stale_staging=args.apply_stale_staging,
        )
        print(json.dumps([item.as_dict() for item in findings], indent=2))
        return 1 if any(not item.removed for item in findings) else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
