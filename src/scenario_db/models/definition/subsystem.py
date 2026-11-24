"""IP-internal subsystems (R-4): the units, streams, stages, routes and wake sources inside one pipeline node.

A node such as ABOX is not one load: CA32 cores, a HiFi DSP, DMA and audio interfaces share a clock domain,
process periodic streams and wake the AP. ``PipelineNode.subsystem`` describes that inside; the evaluator
``mcps-v1`` (sim/subsystem.py) turns it into the node's power, clock and deadline slack, replacing its
``domain_load``. A variant patches it at ``node_configs.<node>.sim.subsystem`` (deep merge, ``$items`` by id).
Absent = None: the node keeps its ``domain_load`` and every stored document / hash stays as before.

Numbers are plain literals (MCPS = million cycles per second, the unit audio DSP vendors quote).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel
from scenario_db.models.definition.job import Selector

UnitKind = Literal["cpu", "dsp", "hw", "memory", "interface"]
StageKind = Literal["dma", "mixer", "src", "effect", "codec", "solution", "interface", "detector"]
COMPUTE_KINDS = ("cpu", "dsp")


class SubsystemUnit(BaseScenarioModel):
    id: str = Field(min_length=1)
    kind: UnitKind
    clock_domain: str | None = None               # units on one clock (AUD); None = a domain of its own
    freqs_mhz: list[float] | None = None          # operating points; None = the node's IP catalog DVFS levels
    # cpu / dsp: util-vf-v1 coefficients {coeff_uw_per_mhz_v2, vf, leakage, idle_gated}; hw / memory /
    # interface: {mw: constant}. None = not attributed (reported, not counted as 0).
    power: dict[str, Any] | None = None
    target_util: float = Field(default=0.85, ge=0.05, le=1.0)
    value_source: str = "assumed"
    basis: str | None = None

    @model_validator(mode="after")
    def _check(self) -> SubsystemUnit:
        if self.freqs_mhz is not None and (not self.freqs_mhz or any(f <= 0 for f in self.freqs_mhz)):
            raise ValueError(f"unit {self.id}: freqs_mhz must be positive MHz values")
        p = self.power
        if p is not None:
            if self.kind in COMPUTE_KINDS:
                if "mw" in p:
                    raise ValueError(f"unit {self.id}: a {self.kind} unit takes util-vf-v1 power, not a constant mw")
                if not p.get("coeff_uw_per_mhz_v2") or not p.get("vf"):
                    raise ValueError(f"unit {self.id}: power needs coeff_uw_per_mhz_v2 and vf")
            elif set(p) - {"mw", "value_source", "basis"} or not isinstance(p.get("mw"), (int, float)) \
                    or isinstance(p.get("mw"), bool) or p["mw"] < 0:
                raise ValueError(f"unit {self.id}: a {self.kind} unit takes power {{mw: >= 0}}")
        return self


class SubsystemStream(BaseScenarioModel):
    id: str = Field(min_length=1)
    fs_hz: int = Field(gt=0)
    channels: int = Field(gt=0)
    bits: int = Field(gt=0)
    period_frames: int = Field(gt=0)              # period_ms = period_frames / fs_hz x 1000
    periods: int = Field(default=2, ge=1)         # buffer depth: latency and deadline headroom
    buffer: Literal["sram", "dram"] = "dram"

    @property
    def period_ms(self) -> float:
        return self.period_frames / self.fs_hz * 1000.0


class SubsystemStage(Selector):
    id: str = Field(min_length=1)
    kind: StageKind
    on: str = Field(min_length=1)                 # unit id
    stream: str | None = None
    mcps: float | None = Field(default=None, ge=0)                 # load at this stream format
    mcycles_per_period: float | None = Field(default=None, ge=0)   # or work per stream period
    bind: str | None = None                       # pipeline node the result is shown on (attribution only)
    value_source: str = "assumed"
    basis: str | None = None
    evidence_ref: str | None = None

    @model_validator(mode="after")
    def _check(self) -> SubsystemStage:
        if self.mcps is not None and self.mcycles_per_period is not None:
            raise ValueError(f"stage {self.id}: give mcps or mcycles_per_period, not both")
        if self.mcycles_per_period is not None and self.stream is None:
            raise ValueError(f"stage {self.id}: mcycles_per_period needs the stream it runs per period of")
        return self


class WakeSource(Selector):
    kind: Literal["period_irq", "refill", "event"]
    stream: str | None = None                     # period_irq: one wake per period of this stream
    every_ms: float | None = Field(default=None, gt=0)   # refill period
    mb: float | None = Field(default=None, ge=0)          # DRAM read per refill
    per_s: float | None = Field(default=None, ge=0)       # event rate

    @model_validator(mode="after")
    def _check(self) -> WakeSource:
        need = {"period_irq": "stream", "refill": "every_ms", "event": "per_s"}[self.kind]
        if getattr(self, need) is None:
            raise ValueError(f"wake {self.kind} needs {need}")
        return self


class SubsystemRoute(Selector):
    id: str = Field(min_length=1)
    kind: Literal["playback", "capture", "duplex"]
    stages: list[str] = Field(min_length=1)       # linear path; consecutive stages must be an edge
    latency_target_ms: float | None = Field(default=None, gt=0)


def _dups(ids: list[str]) -> list[str]:
    return sorted({i for i in ids if ids.count(i) > 1})


class SubsystemSpec(BaseScenarioModel):
    model: str = "mcps-v1"
    units: list[SubsystemUnit] = Field(min_length=1)
    streams: list[SubsystemStream] | None = None
    stages: list[SubsystemStage] | None = None
    edges: list[list[str]] | None = None          # [from, to] stage pairs: connectivity only
    routes: list[SubsystemRoute] | None = None
    wake: list[WakeSource] | None = None
    sram_kb: float | None = Field(default=None, ge=0)
    value_source: str = "assumed"
    basis: str | None = None

    @model_validator(mode="after")
    def _references(self) -> SubsystemSpec:
        units = {u.id: u for u in self.units}
        streams = {s.id for s in self.streams or []}
        stages = {s.id for s in self.stages or []}
        for name, ids in (("unit", [u.id for u in self.units]), ("stream", [s.id for s in self.streams or []]),
                          ("stage", [s.id for s in self.stages or []]), ("route", [r.id for r in self.routes or []])):
            dup = _dups(ids)
            if dup:
                raise ValueError(f"subsystem: duplicate {name} ids {dup}")
        for s in self.stages or []:
            if s.on not in units:
                raise ValueError(f"subsystem stage {s.id}: unit '{s.on}' not found")
            if s.stream is not None and s.stream not in streams:
                raise ValueError(f"subsystem stage {s.id}: stream '{s.stream}' not found")
            if (s.mcps or s.mcycles_per_period) and units[s.on].kind not in COMPUTE_KINDS:
                raise ValueError(f"subsystem stage {s.id}: a load needs a cpu / dsp unit, '{s.on}' is "
                                 f"{units[s.on].kind}")
        edges = set()
        for pair in self.edges or []:
            if len(pair) != 2 or any(p not in stages for p in pair):
                raise ValueError(f"subsystem edge {pair}: needs two known stage ids")
            edges.add((pair[0], pair[1]))
        for r in self.routes or []:
            missing = [s for s in r.stages if s not in stages]
            if missing:
                raise ValueError(f"subsystem route {r.id}: unknown stages {missing}")
            broken = [f"{a}->{b}" for a, b in zip(r.stages, r.stages[1:]) if (a, b) not in edges]
            if broken:
                raise ValueError(f"subsystem route {r.id}: {broken} are not edges")
        for w in self.wake or []:
            if w.stream is not None and w.stream not in streams:
                raise ValueError(f"subsystem wake {w.kind}: stream '{w.stream}' not found")
        return self

    def bind_nodes(self) -> set[str]:
        return {s.bind for s in self.stages or [] if s.bind}
