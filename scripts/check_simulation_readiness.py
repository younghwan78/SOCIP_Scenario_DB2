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
from scenario_db.db.repositories.scenario_graph import load_canonical_graph  # noqa: E402
from scenario_db.db.session import get_session  # noqa: E402
from scenario_db.sim.readiness import check_simulation_readiness  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check whether a scenario/variant is ready for simulation.")
    parser.add_argument("scenario_id")
    parser.add_argument("variant_id")
    parser.add_argument("--database-url", default=None, help="Defaults to SCENARIO_DB_DATABASE_URL or DATABASE_URL.")
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _load_env_file(_root / ".env")
    database_url = args.database_url or os.environ.get("SCENARIO_DB_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("SCENARIO_DB_DATABASE_URL or DATABASE_URL is required")

    engine = make_engine(database_url)
    with get_session(engine) as session:
        graph = load_canonical_graph(session, args.scenario_id, args.variant_id)
        report = check_simulation_readiness(graph)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{report['status']}: {report['scenario_id']}/{report['variant_id']} soc={report['soc_id']}")
        for issue in [*report["errors"], *report["warnings"]]:
            target = f" {issue.get('node_id')}" if issue.get("node_id") else ""
            print(f"{issue['severity']}: {issue['code']}{target}: {issue['message']}")
    return 1 if report["status"] == "blocked" else 0


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
