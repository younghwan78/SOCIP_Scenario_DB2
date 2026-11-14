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
