from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

_root = Path(__file__).resolve().parents[1]
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

from scenario_db.sim.exploration import ExplorationSweep, compile_exploration_sweep  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile an exploration sweep into a scenario.import_bundle JSON.")
    parser.add_argument("sweep_yaml", type=Path)
    parser.add_argument("--bundle-output", type=Path, default=None, help="Write scenario.import_bundle JSON.")
    parser.add_argument("--cases-output", type=Path, default=None, help="Write expanded case table JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw = yaml.safe_load(args.sweep_yaml.read_text(encoding="utf-8"))
    sweep = ExplorationSweep.model_validate(raw)
    result = compile_exploration_sweep(sweep)

    if args.bundle_output:
        args.bundle_output.parent.mkdir(parents=True, exist_ok=True)
        args.bundle_output.write_text(
            json.dumps(result.import_bundle, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    if args.cases_output:
        args.cases_output.parent.mkdir(parents=True, exist_ok=True)
        args.cases_output.write_text(
            json.dumps(result.cases, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
