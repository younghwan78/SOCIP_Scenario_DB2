"""S-10: what each exploration engine revision changed and which results it moves.

``ENGINE_REV`` (sim/arch_exploration.py) names the revision a run / prediction was computed with. A result
computed by an older revision is flagged ("이전 engine"); :func:`changes_since` tells the reader what changed
between that revision and today's, so the flag is a reason and not only a number.

Rules (docs/contracts/simulation/engine-revisions.md):
- bump ``ENGINE_REV`` only when the same inputs give a different result; add the entry here in the same change,
  with what moves and by how much on the E2600 fixture (``scripts/check_engine_equivalence.py``).
- an opt-in change (new data opts in, undeclared data gives identical results) keeps the revision; it is listed
  under ``OPT_IN`` instead.
"""

from __future__ import annotations

from typing import TypedDict


class Revision(TypedDict):
    rev: int
    change: str
    moves: str


ENGINE_REVISIONS: list[Revision] = [
    {"rev": 10, "change": "shared CPU load; every output stream is judged",
     "moves": "CPU power and the verdict of variants with several outputs (preview + record)"},
    {"rev": 11, "change": "lossless and lossy compression per buffer; lever analysis",
     "moves": "BW / BW power of compressed buffers; the lever table"},
    {"rev": 12, "change": "SBWC mean ratio = the typical ratio (engine baseline); eligible-only lever path and exact optimum",
     "moves": "BW of SBWC buffers, the recommended combination when a lever was not eligible"},
    {"rev": 13, "change": "the v2-vf clock term uses the work clock (busy share no longer follows the SW margin)",
     "moves": "IP power under the v2-vf power model when SW growth changed"},
    {"rev": 14, "change": "profile CPU model (cpu_sched): opt-in RT cpupri placement; a task's threads on one CPU run in sequence",
     "moves": "CPU power / slack with the profile CPU model"},
    {"rev": 15, "change": "SW margin follows the throughput model (pipelined: longest task / shared-CPU load; the stage chain gives the frames in flight)",
     "moves": "SW margin and SW growth tolerance under the pipelined model (recording: the NRT margin)"},
    {"rev": 16, "change": "one bytes-per-pixel lookup (packed RGBA = 4 B/px; steady, trace and jobs agree); a "
                          "sw_timing IP node's M2M buffer DMA is counted; a buffer with no size is reported",
     "moves": "BW / BW power of RGBA buffers (E2600 game FHD 120: 497.7 -> 1990.7 MB/s, +119 mW; gallery x4), "
              "the m2m-upscale path (0 -> 3926 MB/s), GPU fallback / SW demux writes (SW BW)"},
]

# Opt-in model changes since the last bump: undeclared data gives identical results (check_engine_equivalence:
# 0 differences), so the revision stays.
OPT_IN: list[dict[str, str]] = [
    {"since": "15", "change": "objective order (Pareto policy) and registration rule auto:min-power / auto:objective",
     "opt_in": "an explicit objective order in the request"},
    {"since": "15", "change": "task cadence vocabulary; own cadences judged by their own deadline, own-cadence SW counted as CPU work",
     "opt_in": "node_configs.<node>.timeline.cadence"},
    {"since": "15", "change": "workload load models (codec-throughput-v1 decoder throughput)",
     "opt_in": "sim.load_model / the pipeline node's load_model"},
    {"since": "15", "change": "domain load models (util-vf-v1): GPU / NPU / audio DSP power from a declared work rate; "
                              "a domain-load SW task is not CPU work",
     "opt_in": "the pipeline node's domain_load / node_configs.<node>.sim.domain_load"},
    {"since": "15", "change": "CPU OPP as a timing input: CPU SW runtime and CPU power at a declared cluster frequency "
                              "(lever cpu_opp)",
     "opt_in": "design_conditions.cpu_opp_mhz"},
    {"since": "15", "change": "event jobs (job-v1): a shot / launch / switch on top of the steady frames - latency, "
                              "event energy, peak power / BW / footprint, RT wait and dropped preview frames",
     "opt_in": "pipeline.jobs (report.jobs)"},
    {"since": "15", "change": "IP subsystems (mcps-v1): unit load, clock-domain operating point, power, deadline "
                              "slack, route latency and wake rates inside a node (ABOX), in place of its domain load",
     "opt_in": "the pipeline node's subsystem / node_configs.<node>.sim.subsystem (report.subsystems)"},
    {"since": "15", "change": "mcps-v1 rule 2: the node's dvfs.aud_freq_khz pins the subsystem AUD clock; a hw / "
                              "interface unit without an active stage is gated (0 mW). The rule revision is in the "
                              "condition hash, so subsystem results of rule 1 are stale",
     "opt_in": "the pipeline node's subsystem (E2600 ABOX since R-4b)"},
    {"since": "15", "change": "wake residency (wake-residency-v1): AP wake entry / exit and MIF active / self-refresh "
                              "state power from the subsystems' wake sources",
     "opt_in": "config.residency (sim.config_profile run_config.residency) with a subsystem wake source "
               "(report.residency, power.residency_mw)"},
    {"since": "15", "change": "judgement rate (R-1): request fps > judgement.rate > design_conditions.fps > 30; "
                              "display / audio / file sink kinds",
     "opt_in": "pipeline.judgement.rate (report.fps_source)"},
    {"since": "15", "change": "frame pacing (frame-pacing-v1): CPU / GPU frame chain, BufferQueue back-pressure and "
                              "panel latch (FIFO / mailbox) Monte Carlo - achieved fps, jank, frame time, latency",
     "opt_in": "node_configs.<gpu>.sim.workload.frame_time (report.pacing)"},
]


def rev_number(rev: str | None) -> int | None:
    """``arch-exploration/15`` -> 15 (None when unparsable)."""
    if not rev:
        return None
    tail = str(rev).rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


def changes_since(old_rev: str | None, current_rev: str) -> list[Revision]:
    """The revisions after ``old_rev`` up to ``current_rev`` (oldest first); every known one when unparsable."""
    lo, hi = rev_number(old_rev), rev_number(current_rev)
    if hi is None:
        return []
    return [r for r in ENGINE_REVISIONS if (lo is None or r["rev"] > lo) and r["rev"] <= hi]
