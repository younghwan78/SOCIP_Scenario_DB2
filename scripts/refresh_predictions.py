"""Re-run and re-register every current prediction of one project after an engine / input change.

    python scripts/refresh_predictions.py --project proj-sm-s947b --check     # compute, store nothing
    python scripts/refresh_predictions.py --project proj-sm-s947b             # store runs + registrations

Each registered exploration run is re-run once under its stored condition and its variants are promoted by the
default rule (``scenario_db.api.services.prediction_refresh``). The project is required: a refresh never spans
projects. Regenerate the project review report afterwards (``POST /api/v1/arch/reports {"project_ref": ...}``).
The DB comes from ``SCENARIO_DB_DATABASE_URL`` (same as the API).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _fmt(v: float | None) -> str:
    return "-" if v is None else f"{v:.1f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="project id, e.g. proj-sm-s947b")
    ap.add_argument("--check", action="store_true", help="compute only; roll back (nothing stored)")
    ap.add_argument("--reason", default=None, help="reason recorded on the new predictions")
    ap.add_argument("--user", default="batch-refresh")
    ap.add_argument("--parallel", action="store_true", help="explore variants in the process pool")
    ap.add_argument("--json", type=Path, default=None, help="write the full result as JSON")
    args = ap.parse_args(argv)

    from scenario_db.api.services.prediction_refresh import refresh_project
    from scenario_db.db.base import make_engine
    from scenario_db.db.session import make_session_factory

    with make_session_factory(make_engine())() as db:
        out = refresh_project(db, args.project, user=args.user, check=args.check, reason=args.reason,
                              parallel=args.parallel)
    if args.json:
        args.json.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    mode = "check (not stored)" if out["check"] else "stored"
    print(f"{out['project_ref']} · {out['engine_rev']} · {mode}")
    for r in out["runs"]:
        print(f"  {r['source_run']} -> {r['run_id']}  {r['scenario_type']}: {r['registered']} registered, "
              f"{r['extra']} unregistered re-evaluated")
    for r in out["rows"]:
        if r["status"] not in ("recomputed", "ok", "evaluated"):
            print(f"  {r['status']:<10} {r['scenario_id']}/{r['variant_id']}: {r.get('reason') or ''}")
    deltas = [r for r in out["rows"] if r.get("delta_mw") is not None]
    by_scenario: dict[str, list[float]] = {}
    for r in deltas:
        by_scenario.setdefault(r["scenario_id"], []).append(r["delta_mw"])
    for scenario, ds in sorted(by_scenario.items()):
        print(f"  {scenario}: {len(ds)} · delta min {_fmt(min(ds))} max {_fmt(max(ds))} "
              f"mean {_fmt(sum(ds) / len(ds))} mW")
    print("  " + ", ".join(f"{k} {v}" for k, v in sorted(out["counts"].items())))
    bad = out["counts"].get("skipped", 0) + out["counts"].get("error", 0)
    return 1 if bad else 0


if __name__ == "__main__":  # the process pool (``--parallel``) needs the guard on Windows
    sys.exit(main())
