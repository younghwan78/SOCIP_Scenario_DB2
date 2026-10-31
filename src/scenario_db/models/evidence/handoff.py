"""Hand-off flow document (``sdb.handoff/1``): the in-house hand-off order as data.

One document per full-stack capture. ``participants`` are the sequence-diagram
columns (each in one software/hardware layer), ``cadences`` every rate the
scenario runs at, and ``flows`` the ordered steps of one unit (frame, buffer,
period) crossing those participants. Design: docs/design/handoff-flow-ko.md.
"""
from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from scenario_db.models.common import BaseScenarioModel

HandoffLayer = Literal["app", "framework", "hal", "kernel", "fw", "hw"]
HandoffKind = Literal["kick", "complete", "ipc", "irq", "data"]
CadenceKind = Literal["frame", "vsync", "period", "chunk", "divided", "event"]
_PERIODIC = {"frame", "vsync", "period", "chunk"}


class _Strict(BaseScenarioModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HandoffParticipant(_Strict):
    id: str = Field(min_length=1)
    layer: HandoffLayer
    name: str = Field(min_length=1)
    detail: str | None = None


class HandoffCadence(_Strict):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: CadenceKind
    period_ms: float | None = Field(default=None, gt=0)
    of: str | None = None          # divided: base cadence id
    every: int | None = Field(default=None, ge=2)
    note: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> HandoffCadence:
        if self.kind in _PERIODIC and self.period_ms is None:
            raise ValueError(f"cadence {self.id}: kind {self.kind} needs period_ms")
        if self.kind == "divided" and (self.of is None or self.every is None):
            raise ValueError(f"cadence {self.id}: kind divided needs of and every")
        if self.kind == "event" and self.period_ms is not None:
            raise ValueError(f"cadence {self.id}: kind event has no period_ms")
        return self


class HandoffStep(_Strict):
    """A call (``to`` set, ``from`` optional for the unit's start) or a note (``note`` + ``over``)."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    call: str | None = None
    task: str | None = None        # common name shared with the timing perfetto
    slice: str | None = None       # timeline_events[].task_id of the same evidence
    node: str | None = None        # Pipeline timing node
    handoff: HandoffKind = "data"
    branch: str | None = None      # consecutive steps with the same branch form one par block
    cadence: str | None = None     # set when the step runs on another cadence than its flow
    every: int | None = Field(default=None, ge=2)
    frame_offset: int | None = None
    t_ms: float | None = None
    dur_ms: float | None = Field(default=None, ge=0)
    note: str | None = None
    over: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self) -> HandoffStep:
        if self.note is not None:
            if self.to is not None or self.from_ is not None or not self.over:
                raise ValueError("note step takes note + over only")
        elif self.to is None:
            raise ValueError("call step needs to")
        return self


class HandoffFlow(_Strict):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    cadence: str
    summary: str | None = None
    steps: list[HandoffStep] = Field(min_length=1)


class HandoffDoc(_Strict):
    format: Literal["sdb.handoff/1"]
    generator: str | None = None
    participants: list[HandoffParticipant] = Field(min_length=1)
    cadences: list[HandoffCadence] = Field(min_length=1)
    flows: list[HandoffFlow] = Field(min_length=1)

    @model_validator(mode="after")
    def _references(self) -> HandoffDoc:
        for label, ids in (("participant", [p.id for p in self.participants]), ("cadence", [c.id for c in self.cadences]),
                           ("flow", [f.id for f in self.flows])):
            dup = sorted({i for i in ids if ids.count(i) > 1})
            if dup:
                raise ValueError(f"duplicate {label} id: {', '.join(dup)}")
        parts = {p.id for p in self.participants}
        cads = {c.id for c in self.cadences}
        for c in self.cadences:
            if c.of is not None and (c.of not in cads or c.of == c.id):
                raise ValueError(f"cadence {c.id}: unknown base cadence {c.of}")
        for f in self.flows:
            if f.cadence not in cads:
                raise ValueError(f"flow {f.id}: unknown cadence {f.cadence}")
            for i, s in enumerate(f.steps, 1):
                for ref in [s.from_, s.to, *s.over]:
                    if ref is not None and ref not in parts:
                        raise ValueError(f"flow {f.id} step {i}: unknown participant {ref}")
                if s.cadence is not None and s.cadence not in cads:
                    raise ValueError(f"flow {f.id} step {i}: unknown cadence {s.cadence}")
        return self
