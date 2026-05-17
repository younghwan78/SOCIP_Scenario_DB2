from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scenario_db.sim.chain_templates import compile_chain_template_sweep  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile a chain template sweep YAML into ScenarioDB import-bundle cases.")
    parser.add_argument("sweep_yaml", type=Path)
    parser.add_argument("--bundle-output", type=Path, help="Write import bundle JSON.")
    parser.add_argument("--cases-output", type=Path, help="Write expanded case metadata JSON.")
    args = parser.parse_args()

    payload = yaml.safe_load(args.sweep_yaml.read_text(encoding="utf-8"))
    result = compile_chain_template_sweep(payload)

    if args.bundle_output:
        args.bundle_output.parent.mkdir(parents=True, exist_ok=True)
        args.bundle_output.write_text(json.dumps(result.import_bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.cases_output:
        args.cases_output.parent.mkdir(parents=True, exist_ok=True)
        args.cases_output.write_text(json.dumps(result.cases, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.bundle_output and not args.cases_output:
        print(json.dumps(result.import_bundle, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
