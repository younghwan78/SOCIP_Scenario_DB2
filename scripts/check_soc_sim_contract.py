from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

from scenario_db.sim.fixture_contract import load_fixture_documents, validate_soc_sim_contract  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate SoC fixture simulation contract metadata.")
    parser.add_argument("fixture_root", type=Path, help="Canonical fixture directory containing soc/ip YAML files.")
    parser.add_argument("--soc-id", default=None, help="SoC id to validate when the directory contains multiple SoCs.")
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    documents = load_fixture_documents(args.fixture_root)
    report = validate_soc_sim_contract(documents, soc_id=args.soc_id)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        summary = report.get("summary") or {}
        print(
            f"{report['status']}: {report['soc_id']} "
            f"compute={summary.get('compute_ip_count', 0)} "
            f"external={summary.get('external_ip_count', 0)} "
            f"borrowable={summary.get('borrowable_count', 0)}"
        )
        for issue in [*report["errors"], *report["warnings"], *report["borrowable"]]:
            target = f" {issue.get('ip_ref')}" if issue.get("ip_ref") else ""
            print(f"{issue['severity']}: {issue['code']}{target}: {issue['message']}")
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
