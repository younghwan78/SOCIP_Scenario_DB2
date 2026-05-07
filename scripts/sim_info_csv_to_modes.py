from __future__ import annotations

import argparse
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

from scenario_db.sim.csv_import import (  # noqa: E402
    build_sim_block,
    dump_yaml_fragment,
    load_legacy_sim_info_csv,
    merge_sim_block_into_catalog_yaml,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert legacy project*_info.csv rows into capabilities.sim.modes YAML.",
    )
    parser.add_argument("csv_path", type=Path, help="Legacy project*_info.csv path.")
    parser.add_argument("--hw-name", required=True, help="Legacy HW name to import, e.g. MFC or CSIS.")
    parser.add_argument(
        "--catalog-yaml",
        type=Path,
        help="Optional ip-*.yaml catalog file to update with the generated sim block.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Write the merged catalog YAML back to --catalog-yaml.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write generated YAML to this path instead of stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = load_legacy_sim_info_csv(args.csv_path)
    sim_block = build_sim_block(rows, args.hw_name)

    if args.catalog_yaml:
        rendered = merge_sim_block_into_catalog_yaml(args.catalog_yaml.read_text(encoding="utf-8"), sim_block)
        if args.in_place:
            args.catalog_yaml.write_text(rendered, encoding="utf-8")
            return 0
    else:
        rendered = dump_yaml_fragment({"sim": sim_block})

    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
