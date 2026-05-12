from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

_root = Path(__file__).resolve().parents[1]
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

from scenario_db.sim.exploration import ExplorationRecipe, compile_exploration_recipe  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile an exploration recipe into canonical scenario YAML.")
    parser.add_argument("recipe_yaml", type=Path)
    parser.add_argument("--output", type=Path, default=None, help="Write compiled scenario YAML.")
    parser.add_argument("--bundle-output", type=Path, default=None, help="Write scenario.import_bundle JSON.")
    parser.add_argument("--json", action="store_true", help="Print JSON compile result instead of scenario YAML.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw = yaml.safe_load(args.recipe_yaml.read_text(encoding="utf-8"))
    recipe = ExplorationRecipe.model_validate(raw)
    result = compile_exploration_recipe(recipe)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            yaml.safe_dump(result.scenario, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
    if args.bundle_output:
        args.bundle_output.parent.mkdir(parents=True, exist_ok=True)
        args.bundle_output.write_text(
            json.dumps(result.import_bundle, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print(yaml.safe_dump(result.scenario, sort_keys=False, allow_unicode=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
