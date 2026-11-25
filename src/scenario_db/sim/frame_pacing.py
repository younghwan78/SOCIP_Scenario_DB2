"""M-6 ``frame-pacing-v1``: a seeded Monte Carlo of the game frame chain on top of the Timing Budget result.

Chain per frame k (target period T, vsync V = panel refresh):

    cpu_start_k = max(k*T, cpu_end_{k-1}, release(k - depth))     # frame pacer + BufferQueue back-pressure
    gpu_start_k = max(cpu_end_k, gpu_end_{k-1});  gpu_end_k = gpu_start_k + t_gpu_k
    latch tick m*V: of the frames done by the tick, FIFO presents the oldest, mailbox the newest (the rest drop)
    release(j)  = the tick frame j leaves the screen (replaced) or is dropped

A buffer is held from dequeue (CPU start) until it is replaced on screen, so ``depth`` >= 2.
Jank = a present interval longer than ceil(T / V) vsyncs: 45 fps on 120 Hz (3-3-2 vsyncs) is no jank.
The timeline engine is not changed; this evaluator reads the plan (CPU SW ranges) and the GPU domain load.
"""

from __future__ import annotations

import math
import random
from statistics import median, pstdev
from typing import Any

from scenario_db.sim.workload_spec import FrameTime, WorkloadSpec

MODEL = "frame-pacing-v1"
FRAMES = 600
WARMUP = 30
SEED = 7
Z95, Z99 = 1.645, 2.326
DEFAULT_DEPTH = 3
SHORTFALL = 0.02     # achieved fps below target by more than this = fail (assumed)


def gpu_sampler(median_ms: float, ft: FrameTime | None):
    """(sampler(rng) -> ms, basis dict). Order: histogram > measured percentiles > p99_x log-normal > fixed."""
    if ft is not None and ft.histogram:
        bins = [(float(ms), float(share)) for ms, share in ft.histogram]
        total = sum(s for _, s in bins)
        weights = [s / total for _, s in bins]
        values = [ms for ms, _ in bins]
        return (lambda rng: rng.choices(values, weights)[0]), {"distribution": "histogram", "bins": len(bins)}
    center = median_ms
    sigma = None
    basis: dict[str, Any] = {}
    if ft is not None and ft.p50_ms and not (ft.p99_ms or ft.p95_ms):
        return (lambda rng: ft.p50_ms), {"distribution": "fixed", "from": "measured p50", "median_ms": round(ft.p50_ms, 4)}
    if ft is not None and (ft.p99_ms or ft.p95_ms):
        center = ft.p50_ms or median_ms
        sigma = (math.log(ft.p99_ms / center) / Z99 if ft.p99_ms else math.log(ft.p95_ms / center) / Z95)
        basis = {"distribution": "lognormal", "from": "measured percentiles", "median_ms": round(center, 4)}
    elif ft is not None and ft.p99_x:
        sigma = math.log(ft.p99_x) / Z99
        basis = {"distribution": "lognormal", "from": "p99_x", "median_ms": round(center, 4)}
        if ft.p95_x:
            implied = math.exp(Z95 * sigma)
            basis["p95_x_declared"] = ft.p95_x
            basis["p95_x_implied"] = round(implied, 4)
            basis["p95_x_gap"] = round(implied - ft.p95_x, 4)
    if sigma is None or sigma <= 0:
        return (lambda rng: center), {"distribution": "fixed", "median_ms": round(center, 4)}
    basis["sigma"] = round(sigma, 5)
    return (lambda rng: center * math.exp(rng.gauss(0.0, sigma))), basis


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def simulate(*, period_ms: float, vsync_ms: float, cpu_ranges: list[tuple[float, float, float]],
             gpu_median_ms: float, frame_time: FrameTime | None, depth: int, present_mode: str,
             frames: int = FRAMES, warmup: int = WARMUP, seed: int = SEED) -> dict[str, Any]:
    """The pacing Monte Carlo (pure). ``cpu_ranges``: serial CPU tasks before the GPU, (min, mean, max) ms."""
    from scenario_db.sim.timing_budget import _sample_sw

    if depth < 2:
        raise ValueError("frame pacing needs a BufferQueue depth >= 2 (one buffer on screen, one to render)")
    if not (period_ms > 0 and vsync_ms > 0 and gpu_median_ms > 0):
        raise ValueError("frame pacing needs positive period, vsync and GPU time")
    rng = random.Random(seed)
    sample_gpu, basis = gpu_sampler(gpu_median_ms, frame_time)
    cpu_start = [0.0] * frames
    cpu_ms = [0.0] * frames
    gpu_ms = [0.0] * frames
    gpu_end = [math.inf] * frames
    present = [None] * frames            # tick it was presented at
    release: list[float | None] = [None] * frames
    dropped = [False] * frames
    state = {"tick": 0, "on_screen": None, "next": 0, "computed": 0}

    def advance_tick() -> None:
        """Process the next vsync latch over the frames computed so far."""
        t = state["tick"] * vsync_ms
        ready = [j for j in range(state["next"], state["computed"]) if gpu_end[j] <= t + 1e-9]
        if not ready:
            pending = [gpu_end[j] for j in range(state["next"], state["computed"])]
            if not pending:
                raise RuntimeError("frame pacing: no frame left to present")
            # nothing to latch until the next frame is done: jump to the first vsync after it (a slow frame)
            state["tick"] = max(state["tick"] + 1, math.ceil(min(pending) / vsync_ms - 1e-9))
            return
        state["tick"] += 1
        pick = ready[0] if present_mode == "fifo" else ready[-1]
        for j in ready:
            if j < pick or (present_mode == "mailbox" and j != pick):
                dropped[j] = True
                release[j] = t
        if state["on_screen"] is not None:
            release[state["on_screen"]] = t
        present[pick] = t
        state["on_screen"] = pick
        state["next"] = pick + 1

    end_cpu = end_gpu = 0.0
    for k in range(frames):
        free = 0.0
        if k - depth >= 0:
            while release[k - depth] is None:
                advance_tick()
            free = release[k - depth]
        start = max(k * period_ms, end_cpu, free)
        c = sum(_sample_sw(rng, *r) for r in cpu_ranges)
        g = sample_gpu(rng)
        end_cpu = start + c
        end_gpu = max(end_cpu, end_gpu) + g
        cpu_start[k], cpu_ms[k], gpu_ms[k], gpu_end[k] = start, c, g, end_gpu
        state["computed"] = k + 1
    while state["next"] < frames:
        advance_tick()

    shown = [k for k in range(warmup, frames) if present[k] is not None and not dropped[k]]
    times = [present[k] for k in shown]
    gaps = [b - a for a, b in zip(times, times[1:])]
    expected = math.ceil(period_ms / vsync_ms - 1e-9) * vsync_ms
    janks = sum(1 for g in gaps if g > expected + 1e-6)
    span = (times[-1] - times[0]) if len(times) > 1 else 0.0
    mean_gap = sum(gaps) / len(gaps) if gaps else None
    judged = range(warmup, frames)
    frame = [cpu_ms[k] + gpu_ms[k] for k in judged]
    latency = [present[k] - cpu_start[k] + vsync_ms for k in shown]       # + one scan-out to photon
    r = lambda v: None if v is None else round(v, 4)  # noqa: E731
    return {
        "model": MODEL,
        "frames": frames, "warmup": warmup, "seed": seed,
        "target_fps": round(1000.0 / period_ms, 4), "refresh_hz": round(1000.0 / vsync_ms, 4),
        "depth": depth, "present_mode": present_mode,
        "achieved_fps": round((len(times) - 1) / span * 1000.0, 3) if span > 0 else None,
        "jank_pct": round(100.0 * janks / len(gaps), 3) if gaps else None,
        "janks": janks,
        "drops": sum(1 for k in judged if dropped[k]),
        "expected_interval_ms": round(expected, 4),
        "present_interval_cov": round(pstdev(gaps) / mean_gap, 4) if gaps and mean_gap else None,
        "gpu_ms": {"p50": r(_pct(gpu_ms[warmup:], 0.5)), "p95": r(_pct(gpu_ms[warmup:], 0.95)),
                   "p99": r(_pct(gpu_ms[warmup:], 0.99)), "median_computed": r(gpu_median_ms)},
        "frame_ms": {"p50": r(_pct(frame, 0.5)), "p95": r(_pct(frame, 0.95)), "p99": r(_pct(frame, 0.99))},
        "latency_ms": {"p50": r(median(latency)) if latency else None, "p99": r(_pct(latency, 0.99))},
        "gpu_basis": basis,
    }


def _ancestors(edges: list[dict], node_id: str, active: set[str]) -> list[str]:
    """Upstream active tasks of ``node_id`` over the edges the Timing Budget plan runs (variant topology applied)."""
    pred: dict[str, set[str]] = {}
    for e in edges:
        a, b = str(e.get("from") or e.get("source") or ""), str(e.get("to") or e.get("target") or "")
        pred.setdefault(b, set()).add(a)
    seen: list[str] = []
    stack = [node_id]
    while stack:
        for p in sorted(pred.get(stack.pop(), set())):
            if p in active and p not in seen:
                seen.append(p)
                stack.append(p)
    return seen


def _is_gpu(graph, node: dict) -> bool:
    ip = graph.ip_catalog.get(str(node.get("ip_ref") or ""))
    text = " ".join(str(x or "").lower() for x in (getattr(ip, "category", None), node.get("ip_ref"), node.get("role")))
    return "gpu" in text


def pacing_report(graph, plan: dict, domain: dict, period_ms: float, ranges: dict, options) -> dict[str, Any] | None:
    """``report.pacing`` when a GPU node declares ``sim.workload.frame_time``; None otherwise."""
    from scenario_db.sim.workload_spec import workload_spec

    configs = graph.variant.node_configs or {}
    gpu = None
    for n in graph.pipeline_nodes:
        nid = str(n.get("id"))
        sim = (configs.get(nid) or {}).get("sim") if isinstance(configs.get(nid), dict) else None
        raw = sim.get("workload") if isinstance(sim, dict) else None
        # opt-in: an active GPU node whose workload mapping declares frame_time (other mappings are not parsed)
        if nid in plan["tasks"] and _is_gpu(graph, n) and isinstance(raw, dict) and raw.get("frame_time") is not None:
            gpu = (nid, workload_spec(sim))
            break
    if gpu is None:
        return None
    node, spec = gpu
    assert isinstance(spec, WorkloadSpec)
    est = domain.get(node)
    if not est or not est.get("freq_mhz") or not est.get("rate_hz"):
        return {"model": MODEL, "node": node, "status": "no_gpu_time",
                "reason": f"{node}: frame pacing needs the node's domain load (work and clock)"}
    gpu_median = float(est["work_mcycles_s"] or 0) / float(est["rate_hz"]) / float(est["freq_mhz"]) * 1000.0
    if not gpu_median > 0:
        return {"model": MODEL, "node": node, "status": "no_gpu_time",
                "reason": f"{node}: frame pacing needs positive GPU work per frame (domain load gives 0)"}
    # vsync from the panel (display output role), else any active node with a refresh rate (DPU)
    panel_hz = None
    nodes = sorted(graph.pipeline_nodes, key=lambda n: str(n.get("role") or "") != "display_output")
    for n in nodes:
        sim = (configs.get(str(n.get("id"))) or {}).get("sim")
        if str(n.get("id")) in plan["tasks"] and isinstance(sim, dict) and sim.get("refresh_hz"):
            panel_hz = float(sim["refresh_hz"])
            break
    vsync = 1000.0 / panel_hz if panel_hz else period_ms
    sw = {i["task"]: i for items in plan["sw_items"].values() for i in items if i["kind"] == "sw"}
    cpu = [t for t in _ancestors(plan.get("edges") or graph.pipeline_edges, node, set(plan["tasks"])) if t in sw]
    cpu_ranges = [ranges.get(t) or (sw[t]["runtime_ms"],) * 3 for t in cpu]
    depth = DEFAULT_DEPTH
    buffers = (getattr(graph.scenario, "pipeline", None) or {}).get("buffers") or {}
    for e in graph.pipeline_edges:      # the variant's active GPU output edge (routing switch / patch applied)
        if str(e.get("from")) == node and e.get("buffer") and str(e.get("to")) in plan["tasks"]:
            count = (buffers.get(e["buffer"]) or {}).get("count")
            if count is not None:
                depth = int(count)
                break
    out = simulate(period_ms=period_ms, vsync_ms=vsync, cpu_ranges=cpu_ranges, gpu_median_ms=gpu_median,
                   frame_time=spec.frame_time, depth=depth, present_mode=spec.present_mode)
    target = 1000.0 / period_ms
    achieved = out["achieved_fps"]
    # a sustained shortfall fails (assumed 2 %, or the interval tolerance if larger); single janks are reported
    # (jank_pct) but have no target until R-6 KPI targets
    floor = target * (1.0 - max(SHORTFALL, options.interval_tolerance))
    ok = achieved is not None and achieved >= floor
    return {**out, "node": node, "status": "ok" if ok else "fail", "cpu_tasks": cpu,
            "fail_below_fps": round(floor, 3),
            "gpu_clock_mhz": est["freq_mhz"], "value_source": spec.value_source,
            **({"title_class": spec.title_class} if spec.title_class else {})}
