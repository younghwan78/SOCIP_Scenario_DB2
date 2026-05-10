from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

from scenario_db.db.base import make_engine  # noqa: E402
from scenario_db.db.session import get_session  # noqa: E402
from scenario_db.sim.golden import load_golden_cases, run_golden_case  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run golden simulation regression cases against the DB.")
    parser.add_argument("--case", action="append", dest="case_ids", help="Case id to run. Can be repeated.")
    parser.add_argument("--cases-file", type=Path, default=_root / "simulation_golden_cases.yaml")
    parser.add_argument("--database-url", default=None, help="Defaults to SCENARIO_DB_DATABASE_URL or DATABASE_URL.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable result JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _load_env_file(_root / ".env")
    database_url = args.database_url or os.environ.get("SCENARIO_DB_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("SCENARIO_DB_DATABASE_URL or DATABASE_URL is required")

    cases = load_golden_cases(args.cases_file)
    selected_ids = args.case_ids or list(cases)
    unknown = [case_id for case_id in selected_ids if case_id not in cases]
    if unknown:
        raise SystemExit(f"Unknown golden case(s): {', '.join(unknown)}")

    results: list[dict] = []
    engine = make_engine(database_url)
    with get_session(engine) as session:
        for case_id in selected_ids:
            result, diffs = run_golden_case(session, cases[case_id])
            results.append(
                {
                    "case": case_id,
                    "status": "failed" if diffs else "passed",
                    "diffs": diffs,
                    "kpi": {
                        "total_power_mw": result.total_power_mw,
                        "total_bw_mbs": result.bw_total_mbs,
                        "hw_time_max_ms": result.hw_time_max_ms,
                        "timeline_end_ms": result.timeline_end_ms,
                    },
                }
            )

    if args.json:
        print(json.dumps({"results": results}, indent=2, sort_keys=True))
    else:
        for item in results:
            print(f"{item['status']}: {item['case']}")
            for diff in item["diffs"]:
                print(f"  {diff['field']}: {diff['reason']} expected={diff.get('expected')} actual={diff.get('actual')}")
    return 1 if any(item["status"] == "failed" for item in results) else 0


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    raise SystemExit(main())
