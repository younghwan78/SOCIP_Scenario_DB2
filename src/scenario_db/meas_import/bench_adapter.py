"""Bench export (per-run wide rail tables) -> ``meas_import`` rail_long CSV.

A power bench exports one wide table per run: rails as rows, Voltage /
Current / Power as columns. ``meas_import`` consumes the long format
(``run,rail,voltage_v,current_ma,power_mw``). This adapter concatenates N
wide files (or one file carrying a run column) into that long CSV, so real
captures load turnkey. Spec anchor: ``examples/measurement-import/BENCH-ADAPTER.md``.

The open format questions (delimiter, header spelling, units, run mapping)
are absorbed as parse-time flexibility instead of hardcoded assumptions:

- delimiter: comma / tab / whitespace, sniffed per file from the header line
- header: any line containing voltage+current+power tokens (case-insensitive);
  earlier title lines are ignored; the rail column is the one named
  rail/name/net/signal, else the first unrecognized column
- units: read from the header suffix (``Voltage(mV)``, ``Power[W]``,
  ``current_ma`` ...); missing suffixes default to V / mA / mW
- runs: a ``run`` column wins; otherwise one file = one run, numbered by the
  first integer in each filename when unique, else by sorted file order

CLI::

    python -m scenario_db.meas_import.bench_adapter \
      --in bench_export_dir --out rail_power_by_run.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from scenario_db.legacy_import.report import ImportReport

LONG_HEADER = ("run", "rail", "voltage_v", "current_ma", "power_mw")

_BENCH_GLOBS = ("*.csv", "*.txt", "*.tsv")

# column-kind detection: token match on the header cell with an optional
# unit suffix in (), [], or a trailing _unit.
_UNIT_SUFFIX = r"(?:\s*[(\[]\s*(?P<unit>[a-zA-Z]+)\s*[)\]]|_(?P<unit2>[a-zA-Z]+))?\s*$"
_COLUMN_KINDS: tuple[tuple[str, str], ...] = (
    ("voltage", r"^\s*volt(?:age)?"),
    ("current", r"^\s*current"),
    ("power", r"^\s*power"),
    ("run", r"^\s*run(?:\s*(?:id|no|number))?\s*$"),
    ("rail", r"^\s*(?:rail|name|net|signal|domain_rail)\s*$"),
)

# scale factors into the canonical units (V / mA / mW)
_UNIT_SCALES: dict[str, dict[str, float]] = {
    "voltage": {"v": 1.0, "mv": 1e-3, "uv": 1e-6},
    "current": {"ma": 1.0, "a": 1e3, "ua": 1e-3},
    "power": {"mw": 1.0, "w": 1e3, "uw": 1e-3},
}
_DEFAULT_UNITS = {"voltage": "v", "current": "ma", "power": "mw"}


class BenchParseError(Exception):
    """Raised when a bench export cannot be parsed unambiguously."""


@dataclass
class _Column:
    kind: str
    index: int
    scale: float = 1.0


@dataclass
class BenchTable:
    """One parsed wide table: rows of canonical-unit rail measurements."""

    source: str
    rows: list[dict] = field(default_factory=list)  # {rail, voltage_v, current_ma, power_mw[, run]}
    has_run_column: bool = False


def _sniff_delimiter(line: str) -> str | None:
    """Return ',' or '\\t' when they dominate; None means whitespace split."""
    if line.count(",") >= 2:
        return ","
    if line.count("\t") >= 2:
        return "\t"
    return None


def _split(line: str, delimiter: str | None) -> list[str]:
    if delimiter is None:
        return line.split()
    return [cell.strip() for cell in line.split(delimiter)]


def _classify_header_cell(cell: str) -> tuple[str, str | None] | None:
    text = cell.strip().strip('"').strip("'")
    for kind, pattern in _COLUMN_KINDS:
        match = re.match(pattern + _UNIT_SUFFIX, text, flags=re.IGNORECASE)
        if match:
            groups = match.groupdict()
            unit = (groups.get("unit") or groups.get("unit2") or "").lower() or None
            return kind, unit
    return None


def _scale_for(kind: str, unit: str | None, *, source: str) -> float:
    if kind not in _UNIT_SCALES:
        return 1.0
    effective = unit or _DEFAULT_UNITS[kind]
    scales = _UNIT_SCALES[kind]
    if effective not in scales:
        raise BenchParseError(
            f"{source}: unsupported {kind} unit '{unit}' (supported: {sorted(scales)})"
        )
    return scales[effective]


def _find_header(lines: list[str], *, source: str) -> tuple[int, str | None, dict[str, _Column]]:
    """Locate the header line: the first line naming voltage+current+power."""
    for idx, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        delimiter = _sniff_delimiter(line)
        cells = _split(line, delimiter)
        kinds: dict[str, _Column] = {}
        unknown: list[int] = []
        for col_idx, cell in enumerate(cells):
            classified = _classify_header_cell(cell)
            if classified is None:
                unknown.append(col_idx)
                continue
            kind, unit = classified
            if kind not in kinds:  # first match wins
                scale = _scale_for(kind, unit, source=source)
                kinds[kind] = _Column(kind=kind, index=col_idx, scale=scale)
        if {"voltage", "current", "power"} <= set(kinds):
            if "rail" not in kinds:
                if not unknown:
                    raise BenchParseError(
                        f"{source}: header line {idx + 1} has no rail column"
                    )
                kinds["rail"] = _Column(kind="rail", index=unknown[0])
            return idx, delimiter, kinds
    raise BenchParseError(
        f"{source}: no header line with voltage/current/power columns found"
    )


def _parse_number(cell: str, *, source: str, line_no: int, name: str) -> float:
    try:
        return float(cell.replace(",", ""))
    except ValueError as exc:
        raise BenchParseError(
            f"{source}: line {line_no}: {name} value is not numeric: {cell!r}"
        ) from exc


def parse_bench_wide(text: str, *, source: str = "<bench>") -> BenchTable:
    """Parse one bench wide export into canonical-unit rows."""
    lines = text.splitlines()
    header_idx, delimiter, columns = _find_header(lines, source=source)
    table = BenchTable(source=source, has_run_column="run" in columns)
    needed = max(col.index for col in columns.values()) + 1

    for line_no, line in enumerate(lines[header_idx + 1 :], start=header_idx + 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = _split(line, delimiter)
        if len(cells) < needed:
            raise BenchParseError(
                f"{source}: line {line_no}: expected at least {needed} columns, got {len(cells)}"
            )
        rail = cells[columns["rail"].index].strip().strip('"')
        if not rail:
            raise BenchParseError(f"{source}: line {line_no}: empty rail name")
        row: dict = {
            "rail": rail,
            "voltage_v": _parse_number(
                cells[columns["voltage"].index], source=source, line_no=line_no, name="voltage"
            )
            * columns["voltage"].scale,
            "current_ma": _parse_number(
                cells[columns["current"].index], source=source, line_no=line_no, name="current"
            )
            * columns["current"].scale,
            "power_mw": _parse_number(
                cells[columns["power"].index], source=source, line_no=line_no, name="power"
            )
            * columns["power"].scale,
        }
        if table.has_run_column:
            run_cell = cells[columns["run"].index]
            row["run"] = int(_parse_number(run_cell, source=source, line_no=line_no, name="run"))
        table.rows.append(row)

    if not table.rows:
        raise BenchParseError(f"{source}: no data rows after the header")
    return table


def _run_number_from_name(path: Path) -> int | None:
    match = re.search(r"(\d+)", path.stem)
    return int(match.group(1)) if match else None


def assign_run_numbers(paths: list[Path]) -> dict[Path, int]:
    """One file = one run. Filename digits win when unique, else sorted order."""
    by_name = {path: _run_number_from_name(path) for path in paths}
    numbers = [n for n in by_name.values() if n is not None]
    if len(numbers) == len(paths) and len(set(numbers)) == len(paths):
        return {path: n for path, n in by_name.items() if n is not None}
    return {path: idx for idx, path in enumerate(sorted(paths), start=1)}


def collect_bench_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        files = sorted(
            {path for pattern in _BENCH_GLOBS for path in target.glob(pattern)}
        )
        return files
    return []


def bench_files_to_rail_long(
    paths: list[Path],
    out_path: Path,
    *,
    report: ImportReport,
) -> bool:
    """Convert N wide bench exports into one rail_long CSV. True on success."""
    if not paths:
        report.error("bench_no_input_files", "No bench export files to convert.")
        return False

    tables: list[BenchTable] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            report.error("bench_file_unreadable", f"Cannot read bench file: {exc}", str(path))
            return False
        try:
            tables.append(parse_bench_wide(text, source=path.name))
        except BenchParseError as exc:
            report.error("bench_parse_failed", str(exc), str(path))
            return False

    with_run = [t for t in tables if t.has_run_column]
    if with_run and len(tables) > 1:
        report.error(
            "bench_mixed_run_semantics",
            "A file with a run column must be the only input; got multiple files.",
            with_run[0].source,
        )
        return False

    long_rows: list[dict] = []
    if with_run:
        long_rows = list(tables[0].rows)
    else:
        run_numbers = assign_run_numbers(paths)
        for path, table in zip(paths, tables):
            run = run_numbers[path]
            for row in table.rows:
                long_rows.append({**row, "run": run})

    rails_by_run: dict[int, set[str]] = {}
    for row in long_rows:
        rails_by_run.setdefault(row["run"], set()).add(row["rail"])
    rail_sets = list(rails_by_run.values())
    if any(rails != rail_sets[0] for rails in rail_sets[1:]):
        # rail_long aggregation would reject this later anyway; surface the
        # inconsistency at the adapter with run context instead.
        report.warning(
            "bench_inconsistent_rail_sets",
            "Runs do not share an identical rail set: "
            + ", ".join(
                f"run {run}: {len(rails)} rails" for run, rails in sorted(rails_by_run.items())
            ),
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(LONG_HEADER)
        for row in sorted(long_rows, key=lambda r: (r["run"],)):
            writer.writerow(
                [
                    row["run"],
                    row["rail"],
                    _fmt(row["voltage_v"]),
                    _fmt(row["current_ma"]),
                    _fmt(row["power_mw"]),
                ]
            )

    report.info(
        "bench_converted",
        f"Converted {len(tables)} bench file(s) / {len(rails_by_run)} run(s) / "
        f"{len(long_rows)} rows into rail_long CSV.",
        str(out_path),
    )
    report.increment("bench_files", len(tables))
    report.increment("rail_long_rows", len(long_rows))
    return True


def _fmt(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert per-run wide bench power exports into a meas_import rail_long CSV.",
    )
    parser.add_argument(
        "--in",
        dest="inputs",
        type=Path,
        nargs="+",
        required=True,
        help="Bench export files, or a directory containing them (*.csv/*.txt/*.tsv).",
    )
    parser.add_argument("--out", type=Path, required=True, help="Output rail_long CSV path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = ImportReport()

    paths: list[Path] = []
    for target in args.inputs:
        found = collect_bench_files(target)
        if not found:
            report.error("bench_input_not_found", f"No bench files at: {target}", str(target))
        paths.extend(found)

    ok = report.ok and bench_files_to_rail_long(paths, args.out, report=report)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return 0 if ok and report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
