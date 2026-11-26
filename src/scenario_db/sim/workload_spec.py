"""R-5: the GPU workload a scenario node declares (``node_configs.<gpu>.sim.workload``).

A string ``sim.workload`` stays a free label (``render``, ``composition``); a mapping is a ``WorkloadSpec``.
The inputs only: the model choice stays the node's ``domain_load.model`` (util-vf-v1 today; pass-roofline-v1
is M-8). Unset fields are None, so a variant without a workload keeps its hash and results.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from scenario_db.models.common import BaseScenarioModel

Positive = Field(default=None, gt=0, allow_inf_nan=False)


class FrameTime(BaseScenarioModel):
    """GPU frame-time spread. Measured values win: ``histogram``, then ``p50/p95/p99_ms``; otherwise
    ``p99_x`` (P99 / median of the computed frame time, assumed) sets a log-normal sigma = ln(p99_x) / 2.326.
    ``p95_x`` only checks that sigma (one sigma cannot match two ratios; the difference is reported)."""

    p50_ms: float | None = Positive
    p95_ms: float | None = Positive
    p99_ms: float | None = Positive
    p99_x: float | None = Field(default=None, ge=1.0, allow_inf_nan=False)
    p95_x: float | None = Field(default=None, ge=1.0, allow_inf_nan=False)
    histogram: list[tuple[float, float]] | None = None   # [[ms, share], ...]

    @field_validator("histogram")
    @classmethod
    def _histogram(cls, value):
        if value is None:
            return value
        if not value:
            raise ValueError("frame_time.histogram needs at least one [ms, share] bin")
        for ms, share in value:
            if not (math.isfinite(ms) and ms > 0 and math.isfinite(share) and share >= 0):
                raise ValueError("frame_time.histogram bins are [ms > 0, share >= 0]")
        if sum(s for _, s in value) <= 0:
            raise ValueError("frame_time.histogram shares sum to zero")
        return value

    @model_validator(mode="after")
    def _ordered(self) -> FrameTime:
        given = [v for v in (self.p50_ms, self.p95_ms, self.p99_ms) if v is not None]
        if given != sorted(given):
            raise ValueError("frame_time p50_ms <= p95_ms <= p99_ms")
        return self


class GpuTraffic(BaseScenarioModel):
    """M-7 L0 GPU DRAM traffic per frame, DRAM side (after compression), MB. Excludes the buffers the scenario
    already carries as pipeline buffers (the framebuffer GPU_DPU_BUF …): those keep their own ports."""

    read: float = Field(ge=0, allow_inf_nan=False)
    write: float = Field(ge=0, allow_inf_nan=False)
    llc_weight: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)   # DRAM share; None = no LLC


class WorkloadSpec(BaseScenarioModel):
    """``node_configs.<gpu>.sim.workload`` as a mapping (R-5). ``frame_time`` turns on frame-pacing-v1;
    ``mb_per_frame`` adds the GPU's own DRAM traffic (M-7); ``mif_floor`` picks the MIF min-lock source."""

    title_class: str | None = None
    frame_time: FrameTime | None = None
    present_mode: Literal["fifo", "mailbox"] = "fifo"
    mb_per_frame: GpuTraffic | None = None
    mif_floor: Literal["catalog", "none"] = "catalog"
    value_source: str = "assumed"
    note: str | None = None


def workload_spec(sim: Any) -> WorkloadSpec | None:
    """The node's declared workload, or None (absent, or a plain label string)."""
    raw = sim.get("workload") if isinstance(sim, dict) else None
    return WorkloadSpec.model_validate(raw) if isinstance(raw, dict) else None
