"""Event jobs (R-3): a one-off or burst piece of work on top of a scenario's steady frame DAG.

A capture shot, a camera launch, a lens switch or a seek is not a frame-rate load. ``pipeline.jobs`` describes
it as a stage DAG (frames x passes x size per stage) whose stages run on the same pipeline nodes as the steady
DAG. This module is the definition layer only: structure and static checks. Numbers may be knob parameter
expressions (``"zsl_frames"``, ``"zsl_frames * 2"``) resolved per variant from ``power_options.params`` /
``param_rules`` / ``design_conditions`` (the knob rules); string fields take ``{param: name}``.

Data flow: a stage reads the job buffers its direct predecessors (in the active DAG, after ``when`` selection)
wrote, plus the buffers whose ``to`` names it; ``reads`` lists session (``pipeline.buffers``) buffers only.
"""

from __future__ import annotations

import ast
import math
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, model_validator

from scenario_db.models.common import BaseScenarioModel



def _strict_num(value: Any) -> Any:
    """Before coercion: a bool is not a number (pydantic would make it 1 / 0), a literal must be finite."""
    if isinstance(value, bool):
        raise ValueError(f"{value!r} is not a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{value!r} is not a finite number")
    return value


Num = Annotated[float | int | str, BeforeValidator(_strict_num)]   # number, or a knob parameter expression
IP_PARAM_KEYS = ("ppc", "unit_power_mw_mp")
ParamRef = str | dict[str, str]    # literal, or {param: name}

_EXPR_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)


def expression_names(value: Any, where: str) -> set[str]:
    """Parameter names of a numeric field; raises on anything but + - * / over names and numbers."""
    if isinstance(value, bool):
        raise ValueError(f"{where}: {value!r} is not a number")
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError(f"{where}: {value!r} is not a finite number")
        return set()
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: {value!r} is not a number or a parameter expression")
    try:
        tree = ast.parse(value, mode="eval")
    except SyntaxError:
        raise ValueError(f"{where}: invalid expression {value!r}") from None
    names: set[str] = set()

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            walk(node.body)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            if not math.isfinite(node.value):
                raise ValueError(f"{where}: {value!r} is not a finite number")
            return
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, _EXPR_OPS):
            walk(node.left)
            walk(node.right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            walk(node.operand)
        else:
            raise ValueError(f"{where}: unsupported expression {value!r} (numbers, names, + - * /)")

    walk(tree)
    return names


def steady_pipeline(pipeline: dict[str, Any] | None) -> dict[str, Any]:
    """The pipeline without ``jobs``: what steady results depend on (fingerprints, input hashes)."""
    return {k: v for k, v in (pipeline or {}).items() if k != "jobs"}


def steady_power_options(options: dict[str, Any] | None) -> dict[str, Any] | None:
    """``power_options`` as steady results see them: without architecture knobs, ``params`` / ``param_rules``
    only parameterize event jobs, so they are left out."""
    if not options:
        return options
    if options.get("knobs"):
        return options
    rest = {k: v for k, v in options.items() if k not in ("params", "param_rules")}
    return rest or None


def const_value(value: Any, where: str) -> float | None:
    """The value of a parameter-free numeric expression (None when it names parameters)."""
    if not isinstance(value, str) or expression_names(value, where):
        return None
    try:
        out = float(eval(compile(ast.parse(value, mode="eval"), where, "eval"), {"__builtins__": {}}, {}))
    except ZeroDivisionError:
        raise ValueError(f"{where}: {value!r} divides by zero") from None
    if not math.isfinite(out):
        raise ValueError(f"{where}: {value!r} is not a finite number")
    return out


def literal_value(value: Any, where: str) -> float | None:
    """A number literal or a parameter-free expression, as a float (None when it names parameters)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return const_value(value, where)


def param_ref_name(value: Any, where: str) -> str | None:
    if value is None or isinstance(value, str):
        return None
    if isinstance(value, dict) and set(value) == {"param"} and isinstance(value["param"], str) and value["param"]:
        return value["param"]
    raise ValueError(f"{where}: expected a string or {{param: name}}, got {value!r}")


# Literal ranges by field (expressions are checked by the evaluator once resolved, with the same rule)
_COUNT = {"frames", "passes", "tiles", "count", "max_in_flight", "bitdepth"}      # integer >= 1
_POSITIVE = {"interval_ms", "max_line_px", "mb", "mb_per_s", "ppc"}              # > 0
# everything else (times, cycles, power, overlap, setup, at_ms, unit power) is >= 0; clock.<group> is > 0


def range_error(path: str, value: float, key: str | None = None) -> str | None:
    """Why ``value`` is out of range for the job field ``path`` (dotted, for the message), or None. ``key``
    is the field kind (its name; ``clock`` for a clock group), default the last path segment."""
    key = key or path.rsplit(".", 1)[-1]
    if key in _COUNT:
        if value < 1 or value != int(value):
            return f"{path} {value} must be an integer >= 1"
    elif key in _POSITIVE or key == "clock":
        if value <= 0:
            return f"{path} {value} must be > 0"
    elif value < 0:
        return f"{path} {value} must be >= 0"
    return None

class Selector(BaseScenarioModel):
    """Variant selection shared by jobs and stages (the knob ``_match`` rule)."""

    when: dict[str, Any] | None = None           # design_conditions match: value or list of values
    when_node_enabled: str | None = None          # node not disabled by the variant's routing_switch


class AfterRef(BaseScenarioModel):
    stage: str = Field(min_length=1)
    per: Literal["stage", "frame"] = "stage"      # frame: consumer chunk k after producer chunk k


class JobChunk(BaseScenarioModel):
    by: Literal["frame", "stripe", "tile"] = "frame"
    max_line_px: Num | None = None                # stripe: IP line buffer width (assumed)
    overlap_px: Num = 0
    tiles: Num | None = None
    setup_us: Num = 0                             # per-chunk boundary overhead


class DomainWork(BaseScenarioModel):
    mcycles: Num | None = None
    mcycles_per_mp: Num | None = None

    @model_validator(mode="after")
    def _one(self) -> DomainWork:
        if (self.mcycles is None) == (self.mcycles_per_mp is None):
            raise ValueError("domain work needs exactly one of mcycles / mcycles_per_mp")
        return self


class SwWork(BaseScenarioModel):
    runtime_ms: Num
    cluster: str | None = None


class TransferWork(BaseScenarioModel):
    mb: Num
    mb_per_s: Num
    power_mw: Num | None = None


class FixedWork(BaseScenarioModel):
    duration_ms: Num
    power_mw: Num | None = None


class SensorWork(BaseScenarioModel):
    switch_in_ms: Num = 0
    switch_out_ms: Num = 0


StageKind = Literal["hw", "domain", "sw", "transfer", "fixed", "sensor"]
_WORK: dict[str, type[BaseScenarioModel] | None] = {
    "hw": None, "domain": DomainWork, "sw": SwWork, "transfer": TransferWork, "fixed": FixedWork, "sensor": SensorWork,
}
_WORK_REQUIRED = {"domain", "sw", "transfer", "fixed"}


class JobStage(Selector):
    id: str = Field(min_length=1)
    phase: str = Field(min_length=1)
    kind: StageKind = "hw"
    nodes: list[str] = Field(min_length=1)        # 2+ = an OTF group (held together, time of the slowest node)
    holds: list[str] | None = None                # further nodes held for the stage (a sensor stage's CSIS)
    size_ref: str | None = None                   # size anchor (size_profile / knob derived)
    frames: Num = 1
    passes: Num = 1
    mode: ParamRef | None = None                  # hw: catalog sim mode; sensor: sensor mode
    ip_params: dict[str, Any] | None = None       # assumed ppc / unit power when the catalog has no mode
    work: dict[str, Any] | None = None            # typed per kind (DomainWork, SwWork, ...)
    reads: list[str] | None = None                # session buffers (pipeline.buffers) only
    writes: list[str] | None = None
    after: list[str | AfterRef] | None = None
    chunk: JobChunk | None = None
    clock: Literal["steady", "max"] | dict[str, Any] = "steady"   # {CAM: Num, ...} or {dvfs_sn: ParamRef}
    value_source: str = "assumed"
    basis: str | None = None
    evidence_ref: str | None = None

    @model_validator(mode="after")
    def _kind(self) -> JobStage:
        model = _WORK[self.kind]
        if self.work is not None:
            if model is None:
                raise ValueError(f"stage {self.id}: kind {self.kind} takes no work block")
            # keep the normalized block (optional nulls dropped) so input and stored signatures agree
            self.work = model.model_validate(self.work).model_dump(exclude_none=True)
        elif self.kind in _WORK_REQUIRED:
            raise ValueError(f"stage {self.id}: kind {self.kind} needs work")
        if self.kind == "sensor" and self.mode is None:
            raise ValueError(f"stage {self.id}: a sensor stage needs the sensor mode")
        unknown = sorted(set(self.ip_params or {}) - set(IP_PARAM_KEYS))
        if unknown:
            raise ValueError(f"stage {self.id}: ip_params {unknown} are not {list(IP_PARAM_KEYS)}")
        for key, value in (self.ip_params or {}).items():
            expression_names(value, f"stage {self.id}.ip_params.{key}")
        if isinstance(self.clock, dict):
            if not self.clock:
                raise ValueError(f"stage {self.id}: clock must not be empty")
            if "dvfs_sn" in self.clock and len(self.clock) > 1:
                raise ValueError(f"stage {self.id}: clock is either {{dvfs_sn: ...}} or DVFS group clocks")
            for group, value in self.clock.items():
                if group != "dvfs_sn" and isinstance(value, (int, float)) and not isinstance(value, bool) and value <= 0:
                    raise ValueError(f"stage {self.id}: clock.{group} {value} must be > 0")
            sn = self.clock.get("dvfs_sn", "")
            if "dvfs_sn" in self.clock and not ((isinstance(sn, str) and sn) or isinstance(sn, dict)):
                raise ValueError(f"stage {self.id}: clock.dvfs_sn needs a DVFS scenario name or {{param: name}}")
        return self

    def after_ids(self) -> list[str]:
        return [a if isinstance(a, str) else a.stage for a in (self.after or [])]

    def numeric_fields(self) -> list[tuple[str, Any]]:
        """(path, value) of every numeric field that may hold a parameter expression."""
        out: list[tuple[str, Any]] = [("frames", self.frames), ("passes", self.passes)]
        if self.chunk is not None:
            for key in ("max_line_px", "overlap_px", "tiles", "setup_us"):
                value = getattr(self.chunk, key)
                if value is not None:
                    out.append((f"chunk.{key}", value))
        for key, value in (self.work or {}).items():
            if key != "cluster" and value is not None:
                out.append((f"work.{key}", value))
        if isinstance(self.clock, dict):
            out += [(f"clock.{k}", v) for k, v in self.clock.items() if k != "dvfs_sn"]
        out += [(f"ip_params.{k}", v) for k, v in (self.ip_params or {}).items()]
        return out

    def param_refs(self) -> list[tuple[str, str]]:
        out = []
        name = param_ref_name(self.mode, f"stage {self.id}.mode")
        if name:
            out.append(("mode", name))
        if isinstance(self.clock, dict) and "dvfs_sn" in self.clock:
            name = param_ref_name(self.clock["dvfs_sn"], f"stage {self.id}.clock.dvfs_sn")
            if name:
                out.append(("clock.dvfs_sn", name))
        return out


class JobBuffer(BaseScenarioModel):
    size_ref: str | None = None                   # default: the producer stage's size_ref
    format: str | None = None
    bitdepth: Num | None = None
    compression: str | None = None
    mb: Num | None = None                         # explicit size (MB = 10^6 B) instead of anchor x format
    count: Num = 1                                # instances = producer -> consumer token capacity
    to: list[str] | None = None                   # consumers that are not direct successors
    lifetime: Literal["session", "job"] = "job"


class JobTrigger(BaseScenarioModel):
    kind: Literal["event", "burst", "periodic"] = "event"
    at_ms: Num = 0.0                              # event start (ms after the session start)
    count: Num = 1
    interval_ms: Num | None = None                # None = as fast as resources and buffers allow
    max_in_flight: Num = 1


JobKpi = Literal["event_latency", "event_rate", "event_energy", "peak_power", "peak_bw", "peak_footprint",
                 "interval", "start_time"]


class JobSpec(Selector):
    id: str = Field(min_length=1)
    label: str | None = None
    model: str = "job-v1"
    trigger: JobTrigger = Field(default_factory=JobTrigger)
    phases: list[str] | None = None
    stages: list[JobStage] = Field(min_length=1)
    buffers: dict[str, JobBuffer] | None = None
    milestones: dict[str, str] | None = None      # name -> stage id (its end)
    background: Literal["steady", "none"] = "steady"
    preview_priority: Literal["rt", "fifo"] = "rt"
    kpis: list[JobKpi] | None = None

    @model_validator(mode="after")
    def _graph(self) -> JobSpec:
        ids = [s.id for s in self.stages]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"job {self.id}: duplicate stage ids {dup}")
        known = set(ids)
        by_id = {s.id: s for s in self.stages}
        for s in self.stages:
            missing = [a for a in s.after_ids() if a not in known]
            if missing:
                raise ValueError(f"job {self.id}: stage {s.id} after unknown stages {missing}")
            for a in s.after or []:
                if isinstance(a, AfterRef) and a.per == "frame":
                    for st in (s, by_id[a.stage]):
                        if st.chunk is not None and st.chunk.by != "frame":
                            raise ValueError(f"job {self.id}: per-frame after needs frame chunks ({st.id})")
                    mine = literal_value(s.frames, f"job {self.id}.stages.{s.id}.frames")
                    theirs = literal_value(by_id[a.stage].frames, f"job {self.id}.stages.{a.stage}.frames")
                    if mine is not None and theirs is not None and mine > theirs:
                        raise ValueError(f"job {self.id}: stage {s.id} has {mine:g} frames per-frame after "
                                         f"{a.stage} with {theirs:g}")
            if self.phases is not None and s.phase not in self.phases:
                raise ValueError(f"job {self.id}: stage {s.id} phase {s.phase!r} not in phases {self.phases}")
        # acyclic (all stages; removing stages by `when` cannot create a cycle)
        # a stage waits for its `after` stages and for the producers of buffers whose `to` names it
        waits: dict[str, list[str]] = {sid: list(by_id[sid].after_ids()) for sid in ids}
        for s in self.stages:
            for b in s.writes or []:
                for t in ((self.buffers or {}).get(b).to or []) if (self.buffers or {}).get(b) else []:
                    if t in waits and s.id not in waits[t]:
                        waits[t].append(s.id)
        # iterative topological sort (Kahn): no recursion limit, independent of declaration order
        indeg = {sid: len(set(waits[sid])) for sid in ids}
        users: dict[str, list[str]] = {sid: [] for sid in ids}
        for sid in ids:
            for a in set(waits[sid]):
                users[a].append(sid)
        ready = [sid for sid in ids if indeg[sid] == 0]
        seen = 0
        while ready:
            sid = ready.pop()
            seen += 1
            for u in users[sid]:
                indeg[u] -= 1
                if indeg[u] == 0:
                    ready.append(u)
        if seen != len(ids):
            raise ValueError(f"job {self.id}: stage cycle among {sorted(sid for sid in ids if indeg[sid] > 0)}")
        buffers = self.buffers or {}
        for s in self.stages:
            unknown = [b for b in (s.writes or []) if b not in buffers]
            if unknown:
                raise ValueError(f"job {self.id}: stage {s.id} writes undeclared job buffers {unknown}")
        written = {b for st in self.stages for b in (st.writes or [])}
        for name, buf in buffers.items():
            bad = [t for t in (buf.to or []) if t not in known]
            if bad:
                raise ValueError(f"job {self.id}: buffer {name} to unknown stages {bad}")
            if buf.to and name not in written:
                raise ValueError(f"job {self.id}: buffer {name} goes to {buf.to} but no stage writes it")
        for name, sid in (self.milestones or {}).items():
            if sid not in known:
                raise ValueError(f"job {self.id}: milestone {name} names unknown stage {sid}")
        for path, key, value in self.range_fields():
            literal = literal_value(value, f"job {self.id}.{path}")       # literals, and e.g. "2 - 2", "60 / 0"
            if literal is None:
                continue
            problem = range_error(path, literal, key)
            if problem:
                raise ValueError(f"job {self.id}: {problem}")
        for s in self.stages:
            c = s.chunk
            if c is None or c.max_line_px is None:
                continue
            line = literal_value(c.max_line_px, f"job {self.id}.stages.{s.id}.chunk.max_line_px")
            overlap = literal_value(c.overlap_px, f"job {self.id}.stages.{s.id}.chunk.overlap_px")
            if line is not None and overlap is not None and line <= overlap:
                raise ValueError(f"job {self.id}: stage {s.id} chunk.max_line_px must exceed overlap_px")
        return self

    def range_fields(self) -> list[tuple[str, str, Any]]:
        """(path, field kind, value) of every numeric field: the kind decides the range, not the path."""
        out = []
        for path, value in self.numeric_fields():
            stage_part = next((f"stages.{s.id}." for s in self.stages if path.startswith(f"stages.{s.id}.")), "")
            field = path[len(stage_part):]
            out.append((path, "clock" if field.startswith("clock.") else field.rsplit(".", 1)[-1], value))
        return out

    def numeric_fields(self) -> list[tuple[str, Any]]:
        out = [("trigger.at_ms", self.trigger.at_ms), ("trigger.count", self.trigger.count),
               ("trigger.max_in_flight", self.trigger.max_in_flight)]
        if self.trigger.interval_ms is not None:
            out.append(("trigger.interval_ms", self.trigger.interval_ms))
        for s in self.stages:
            out += [(f"stages.{s.id}.{p}", v) for p, v in s.numeric_fields()]
        for name, buf in (self.buffers or {}).items():
            for key in ("bitdepth", "mb", "count"):
                value = getattr(buf, key)
                if value is not None:
                    out.append((f"buffers.{name}.{key}", value))
        return out

    def param_refs(self) -> list[tuple[str, str]]:
        return [(f"stages.{s.id}.{p}", n) for s in self.stages for p, n in s.param_refs()]
