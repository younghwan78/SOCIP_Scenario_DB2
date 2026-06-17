from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

from scenario_db.db.base import make_engine  # noqa: E402
from scenario_db.db.session import get_session  # noqa: E402
from scenario_db.etl.loader import LoaderValidationError, load_yaml_dir  # noqa: E402
from scenario_db.sim.csv_import import apply_sim_import_mapping  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply legacy project*_info.csv unit-power data to catalog YAML and optionally reload DB.",
    )
    parser.add_argument("mapping_yaml", type=Path, help="Mapping YAML file.")
    parser.add_argument("--csv", type=Path, help="Override source_csv from mapping YAML.")
    parser.add_argument("--catalog-root", type=Path, help="Override catalog_root from mapping YAML.")
    parser.add_argument("--dry-run", action="store_true", help="Compute patches without writing catalog YAML.")
    parser.add_argument("--reload-db", action="store_true", help="Run scenario_db.etl.loader after patching.")
    parser.add_argument(
        "--reload-dir",
        type=Path,
        help="Fixture directory to reload. Defaults to catalog_root or mapping parent.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results = apply_sim_import_mapping(
        args.mapping_yaml,
        csv_path=args.csv,
        catalog_root=args.catalog_root,
        dry_run=args.dry_run,
    )
    for result in results:
        status = "changed" if result.changed else "unchanged"
        print(f"{status}: {result.catalog_path} hw={result.hw_name} roles={result.role_count}")

    if args.reload_db:
        if args.dry_run:
            raise SystemExit("--reload-db cannot be used with --dry-run")
        reload_dir = args.reload_dir or args.catalog_root or args.mapping_yaml.parent
        _load_env_file(_root / ".env")
        _load_env_file(args.mapping_yaml.parent / ".env")
        if not (os.environ.get("SCENARIO_DB_DATABASE_URL") or os.environ.get("DATABASE_URL")):
            print("SCENARIO_DB_DATABASE_URL or DATABASE_URL is required for --reload-db", file=sys.stderr)
            return 1
        engine = make_engine()
        try:
            with get_session(engine) as session:
                result = load_yaml_dir(Path(reload_dir), session, validate=True, strict=True)
        except LoaderValidationError as exc:
            print("reload-db validation failed:", file=sys.stderr)
            for message in exc.result.error_messages():
                print(f"  {message}", file=sys.stderr)
            return 1
        loaded = ", ".join(f"{kind}={count}" for kind, count in result.counts.items() if count)
        print(f"reloaded: {Path(reload_dir)} ({loaded or 'no rows'})")
    return 0


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
