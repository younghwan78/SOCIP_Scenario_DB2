"""Configuration-driven adapter: any tabular PMU / trace export -> neutral PMU samples.

In-house exports (simpleperf ``stat --csv``, perfetto SQL query results,
vendor profiler CSVs) differ in column names, counter names, headers and
units. Instead of one parser per tool, a ``pmu.table.sources`` entry in
``meta.yaml`` says how to read each file; the rows become the neutral samples
of ``pmu_digest.py`` (``metric, scope_kind, scope_ref, value, freq_mhz``), so
everything downstream (per-frame CPU profile, residency, comparison) is shared.

Source kinds:

- ``counters``: PMU counters. ``layout: long`` = one counter per row
  (``counter_column`` + ``value_column``, e.g. simpleperf); ``layout: wide`` =
  counters are columns. ``counters`` maps canonical names to the tool's names:
  ``cycles``, ``instructions``, ``stall_cycles``, ``bus_access`` (x
  ``bytes_per_access``), ``bus_bytes``.
- ``freq_residency``: time per CPU/cluster frequency (``freq_column``,
  ``value_column`` = time).
- ``idle_residency``: time per idle state (``state_column``, ``value_column``);
  ``states`` maps state names (regex) to ``active`` / ``clock_gated`` /
  ``power_gated``.

Scope per row: ``task`` (optional; thread/process name mapped to logical tasks
with ``task_rules``) and ``cpu`` (CPU id -> cluster via ``cpu_map``) or
``cluster``. Rows sharing a scope are summed (several threads -> one task).
``thread`` (optional, e.g. the tid column) additionally keeps the cycles per
thread of each task (``cpu_thread_cycles``), so the scheduler what-if can split
a task into its real threads.

Clock-domain residency (``meas_import/clock_residency.py``): a ``freq_residency``
/ ``idle_residency`` source may set ``domain_class`` (``cpu`` default, ``gpu``,
...; scope ``cluster`` = the domain name), ``basis: active`` (time per frequency
while running, e.g. a perfetto cpufreq x cpuidle join) and ``group`` (the PMU
pass / capture part the file belongs to; residency is summed over groups and
their divergence is reported as capture quality).
"""
from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from scenario_db.meas_import.clock_residency import domain_class, sample_metric
from scenario_db.models.common import BaseScenarioModel

CANONICAL_COUNTERS = ("cycles", "instructions", "stall_cycles", "bus_access", "bus_bytes")
_FREQ_TO_MHZ = {"mhz": 1.0, "khz": 1e-3, "hz": 1e-6, "ghz": 1000.0}


class ColumnRef(BaseScenarioModel):
    """Where a scope value comes from: a column (optionally a regex capture) or a constant."""

    column: str | None = None
    value: str | None = None
    regex: str | None = None       # group 1 (or the whole match) of the column value

    @model_validator(mode="after")
    def _one_source(self) -> ColumnRef:
        if (self.column is None) == (self.value is None):
            raise ValueError("scope needs exactly one of column / value")
        if self.regex is not None:
            re.compile(self.regex)
        return self


class TaskRule(BaseScenarioModel):
    match: str                     # regex on the task column value (search)
    task: str

    @model_validator(mode="after")
    def _regex(self) -> TaskRule:
        re.compile(self.match)
        return self


class TableSource(BaseScenarioModel):
    file: str
    kind: Literal["counters", "freq_residency", "idle_residency"] = "counters"
    delimiter: str | None = None               # None = sniff (',', '\t', ';', '|')
    comment_prefix: str | None = "#"
    columns: list[str] | None = None           # names for a headerless file
    header_contains: str | None = None         # skip preamble until a header row with this column
    filter: dict[str, str] = Field(default_factory=dict)   # column -> regex that must match
    layout: Literal["long", "wide"] = "long"
    counter_column: str | None = None
    value_column: str | None = None
    counters: dict[str, list[str]] = Field(default_factory=dict)
    bytes_per_access: float | None = Field(default=None, gt=0)
    task: ColumnRef | None = None
    task_rules: list[TaskRule] = Field(default_factory=list)
    unmapped_task: Literal["keep", "other", "drop"] = "other"
    thread: ColumnRef | None = None            # thread identity (tid / name) inside a task
    cpu: ColumnRef | None = None
    cluster: ColumnRef | None = None
    freq_column: str | None = None
    freq_unit: Literal["mhz", "khz", "hz", "ghz"] = "mhz"
    state_column: str | None = None
    states: dict[str, Literal["active", "clock_gated", "power_gated"]] = Field(default_factory=dict)
    domain_class: str = "cpu"                  # clock_residency.DOMAIN_CLASSES key (residency sources)
    basis: Literal["wall", "active"] = "wall"  # freq_residency: whole capture or running time only
    group: str | None = None                   # capture part (e.g. PMU pass) for residency sources

    @model_validator(mode="after")
    def _kind_fields(self) -> TableSource:
        unknown = set(self.counters) - set(CANONICAL_COUNTERS)
        if unknown:
            raise ValueError(f"unknown canonical counters {sorted(unknown)} (use {list(CANONICAL_COUNTERS)})")
        if (self.cpu is None) == (self.cluster is None):
            raise ValueError(f"{self.file}: give exactly one of cpu / cluster scope")
        domain_class(self.domain_class)
        if self.kind == "counters" and (self.domain_class != "cpu" or self.basis != "wall" or self.group):
            raise ValueError(f"{self.file}: domain_class / basis / group apply to residency sources only")
        if self.kind == "idle_residency" and self.basis != "wall":
            raise ValueError(f"{self.file}: idle_residency is wall-clock (basis: wall)")
        if self.domain_class != "cpu" and (self.cpu is not None or self.task is not None):
            raise ValueError(f"{self.file}: {self.domain_class} residency needs a cluster (domain) scope, no cpu / task")
        if self.kind == "counters":
            if not self.counters:
                raise ValueError(f"{self.file}: counters mapping is required")
            if self.layout == "long" and not (self.counter_column and self.value_column):
                raise ValueError(f"{self.file}: long layout needs counter_column and value_column")
        elif self.kind == "freq_residency":
            if not (self.freq_column and self.value_column):
                raise ValueError(f"{self.file}: freq_residency needs freq_column and value_column")
        elif not (self.state_column and self.value_column and self.states):
            raise ValueError(f"{self.file}: idle_residency needs state_column, value_column and states")
        return self


class TableSpec(BaseScenarioModel):
    sources: list[TableSource] = Field(min_length=1)


# ------------------------------------------------------------------ reading
def _number(text: str) -> float | None:
    cleaned = (text or "").strip().replace(",", "").replace("_", "")
    cleaned = cleaned.rstrip("%")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        match = re.match(r"^[-+]?\d+(\.\d+)?([eE][-+]?\d+)?", cleaned)
        return float(match.group(0)) if match else None


def read_table(path: Path, source: TableSource) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [line for line in text.splitlines()
             if line.strip() and not (source.comment_prefix and line.lstrip().startswith(source.comment_prefix))]
    if source.header_contains and source.columns is None:
        # The header is the first line with a cell equal to that column name
        # (tools print free text before the table).
        for index, line in enumerate(lines):
            cells = [c.strip().strip('"') for c in re.split(r"[,\t;|]", line)]
            if source.header_contains in cells:
                lines = lines[index:]
                break
        else:
            raise ValueError(f"{path.name}: no header row with a '{source.header_contains}' column")
    if not lines:
        return []
    delimiter = source.delimiter
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff("\n".join(lines[:20]), delimiters=",\t;|").delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    rows = [list(r) for r in reader]
    header = source.columns or [h.strip() for h in rows.pop(0)]
    out = []
    for row in rows:
        cells = [c.strip() for c in row] + [""] * max(0, len(header) - len(row))
        record = dict(zip(header, cells))
        if all(re.search(rx, record.get(col, "")) for col, rx in source.filter.items()):
            out.append(record)
    return out


def _scope_value(ref: ColumnRef | None, row: dict[str, str]) -> str | None:
    if ref is None:
        return None
    if ref.value is not None:
        return ref.value
    raw = row.get(ref.column or "", "")
    if ref.regex:
        match = re.search(ref.regex, raw)
        if not match:
            return None
        raw = match.group(1) if match.groups() else match.group(0)
    return raw.strip() or None


def _task(source: TableSource, row: dict[str, str], unmapped: set[str]) -> tuple[bool, str | None]:
    """(keep_row, task). task None = cluster/cpu-level row."""
    if source.task is None:
        return True, None
    raw = _scope_value(source.task, row)
    if raw is None:
        return True, None
    for rule in source.task_rules:
        if re.search(rule.match, raw):
            return True, rule.task
    if not source.task_rules or source.unmapped_task == "keep":
        return True, raw
    unmapped.add(raw)
    if source.unmapped_task == "drop":
        return False, None
    return True, "(other)"


def table_samples(base_dir: Path, spec: TableSpec, warnings: list[str]) -> list[dict]:
    """Neutral sample dicts (summed per identity) from every configured source."""
    totals: dict[tuple[str, str, str, float | None, str], float] = defaultdict(float)
    for source in spec.sources:
        path = Path(source.file)
        path = path if path.is_absolute() else base_dir / path
        rows = read_table(path, source)
        if not rows:
            warnings.append(f"{source.file}: no data rows")
        unmapped: set[str] = set()
        unknown_counters: set[str] = set()
        unknown_states: set[str] = set()
        alias = {name.lower(): canon for canon, names in source.counters.items() for name in [canon, *names]}
        for row in rows:
            keep, task = _task(source, row, unmapped)
            if not keep:
                continue
            place_kind = "cpu" if source.cpu is not None else "cluster"
            place = _scope_value(source.cpu or source.cluster, row)
            if place is None:
                continue
            if place_kind == "cpu":
                digits = re.search(r"\d+", place)
                if digits is None:
                    continue
                place = digits.group(0)
            scope_kind = f"task_{place_kind}" if task else place_kind
            scope_ref = f"{task}@{place}" if task else place

            group = source.group or ""

            def add(metric: str, value: float | None, freq: float | None = None) -> None:
                if value is not None:
                    totals[(metric, scope_kind, scope_ref, freq, group)] += value

            if source.kind == "counters":
                if source.layout == "long":
                    name = row.get(source.counter_column or "", "").strip()
                    canon = alias.get(name.lower())
                    if canon is None:
                        unknown_counters.add(name)
                        continue
                    pairs = [(canon, _number(row.get(source.value_column or "", "")))]
                else:
                    pairs = []
                    for canon, names in source.counters.items():
                        column = next((n for n in [canon, *names] if n in row), None)
                        if column is not None:
                            pairs.append((canon, _number(row[column])))
                thread = _scope_value(source.thread, row) if task else None
                for canon, value in pairs:
                    if canon == "cycles" and thread and value is not None:
                        totals[("cpu_thread_cycles", f"task_thread_{place_kind}", f"{task}#{thread}@{place}", None, "")] += value
                    if canon == "bus_access":
                        if source.bytes_per_access is None:
                            unknown_counters.add("bus_access (bytes_per_access not set)")
                            continue
                        add("cpu_bus_bytes", None if value is None else value * source.bytes_per_access)
                    else:
                        add(f"cpu_{canon}", value)
            elif source.kind == "freq_residency":
                freq = _number(row.get(source.freq_column or "", ""))
                if freq is None or freq <= 0:
                    continue
                add(sample_metric(source.domain_class, "freq", basis=source.basis),
                    _number(row.get(source.value_column or "", "")),
                    round(freq * _FREQ_TO_MHZ[source.freq_unit], 3))
            else:
                state = row.get(source.state_column or "", "").strip()
                target = next((t for rx, t in source.states.items() if re.fullmatch(rx, state)), None)
                if target is None:
                    unknown_states.add(state)
                    continue
                add(sample_metric(source.domain_class, "state", state=target), _number(row.get(source.value_column or "", "")))
        if unmapped:
            warnings.append(f"{source.file}: unmapped tasks -> {source.unmapped_task}: {sorted(unmapped)[:20]}")
        if unknown_counters:
            warnings.append(f"{source.file}: counters not mapped (skipped): {sorted(unknown_counters)[:20]}")
        if unknown_states:
            warnings.append(f"{source.file}: idle states not mapped (skipped): {sorted(unknown_states)[:20]}")
    return [
        {"metric": metric, "scope_kind": kind, "scope_ref": ref, "value": value, "freq_mhz": freq, "group": group}
        for (metric, kind, ref, freq, group), value in sorted(totals.items(), key=lambda kv: tuple(str(x) for x in kv[0]))
    ]
