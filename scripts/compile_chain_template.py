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

from scenario_db.sim.chain_templates import compile_chain_template, normalize_chain_template  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile a compact chain template YAML into a ScenarioDB import bundle.")
    parser.add_argument("template_yaml", type=Path)
    parser.add_argument("--output", type=Path, help="Write normalized scenario YAML.")
    parser.add_argument("--bundle-output", type=Path, help="Write import bundle JSON.")
    parser.add_argument("--normalized-output", type=Path, help="Write normalized chain template YAML.")
    args = parser.parse_args()

    payload = yaml.safe_load(args.template_yaml.read_text(encoding="utf-8"))
    normalized = normalize_chain_template(payload)
    result = compile_chain_template(payload)

    if args.normalized_output:
        args.normalized_output.parent.mkdir(parents=True, exist_ok=True)
        args.normalized_output.write_text(yaml.safe_dump(normalized, sort_keys=False), encoding="utf-8")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(yaml.safe_dump(result.scenario, sort_keys=False), encoding="utf-8")
    if args.bundle_output:
        args.bundle_output.parent.mkdir(parents=True, exist_ok=True)
        args.bundle_output.write_text(json.dumps(result.import_bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.output and not args.bundle_output and not args.normalized_output:
        print(yaml.safe_dump(result.scenario, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
