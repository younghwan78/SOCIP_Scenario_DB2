"""Event job evaluator ``job-v1`` (R-3 / M-2 · M-3): one shot / launch / switch on top of the steady frame DAG.

Opt-in: runs only for a variant whose scenario declares ``pipeline.jobs`` (models/definition/job.py) and whose
selector matches; everything else in the Timing Budget report is unchanged.

Model (deterministic SimPy run, separate from the steady timeline):

* **Background** — every steady HW task keeps its own physical resource busy for its steady ``hw_ms`` once per
  frame period, at RT priority (0). With ``preview_priority: fifo`` it shares priority 1 with the job.
* **Job chunks** — a stage runs as chunks (frame x pass x stripe / tile) at priority 1 on the same physical
  resources (steady ``resource_id``; an OTF group holds all its nodes). Resources are non-preemptive: a running
  chunk delays an RT release by at most its own length (reported as ``rt_wait_max_ms``).
* **Sensor stage** — one continuous reservation of the sensor (+ ``holds``): switch-in, readout of the frames,
  switch-out. Background frames released on a reserved resource are dropped (``dropped_frames``); the buffer it
  writes is ready at the end of readout.
* **Data flow** — a stage consumes the job buffers its direct predecessors wrote (transitive reduction of the
  active DAG) plus buffers whose ``to`` names it. A buffer with ``count`` k is a pool: the producer's frame i
  waits until the consumer released frame i - k (per-frame consumers) — this is what bounds the footprint.

Costs: ``hw`` chunk time = px / (f x ppc) x (1 + h_blank) + setup; energy = the v1 dynamic term at fps 1 (mJ per
frame-pass: unit_power x MP x (V / 710 mV)^2 / 30). Static and clock terms are not attributed yet (``basis``).
``domain`` runs at util 1 at the stage clock (default the highest operating point) with util-vf-v1 power.
``sw`` / ``transfer`` / ``fixed`` use their declared ``power_mw`` (absent = not attributed). Bytes: written and
consumed buffers per frame (format x bitdepth x compression), session reads per frame.
"""

from __future__ import annotations

import math
from typing import Any

from scenario_db.authoring.knobs import KnobError, _match, eval_expr, variant_params
from scenario_db.models.definition.job import AfterRef, JobSpec, JobStage
from scenario_db.sim.bw_calc import resolve_comp_ratio
from scenario_db.sim.domain_loads import DOMAIN_MODELS, domain_load_config
from scenario_db.sim.power_calc import calc_active_power_mw
from scenario_db.sim.transfers import compression_catalog

MODEL_ID = "job-v1"
PEAK_WINDOW_MS = 10.0
SERIES_DT_MS = 0.5
_BPP = {"YUV420": 1.5, "NV12": 1.5, "P010": 1.5, "YUV422": 2.0, "YUV444": 3.0, "BAYER": 1.0, "RAW": 1.0, "Y": 1.0}


class JobError(ValueError):
    pass


# --------------------------------------------------------------------------- helpers

def _variant_dict(graph) -> dict[str, Any]:
    v = graph.variant
    return {"id": getattr(v, "id", None), "design_conditions": dict(v.design_conditions or {}),
            "routing_switch": dict(v.routing_switch or {})}


def _selected(sel, vdict) -> bool:
    return _match(vdict, {"when": sel.when or {}, "when_node_enabled": sel.when_node_enabled})


class _Params:
    def __init__(self, params: dict[str, Any], where: str):
        self.params, self.where = params, where

    def num(self, value: Any, path: str) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        try:
            return eval_expr(value, self.params)
        except KnobError as exc:
            raise JobError(f"{self.where}.{path}: {exc}") from None

    def text(self, value: Any) -> Any:
        if isinstance(value, dict) and "param" in value:
            return self.params.get(value["param"])
        return value


OVERRIDE_FIELDS = {"service_ms", "clock_mhz", "mb", "value_source", "evidence_ref", "basis"}


def stage_overrides(graph, job_id: str) -> dict[str, dict[str, Any]]:
    """Variant-local values of ``job_id`` (R-7 slot): ``node_configs.<node>.sim.jobs.<job>.<stage>``, by stage id."""
    out: dict[str, dict[str, Any]] = {}
    for node, cfg in sorted((getattr(graph.variant, "node_configs", None) or {}).items()):
        jobs = ((cfg or {}).get("sim") or {}).get("jobs") or {}
        for sid, values in (jobs.get(job_id) or {}).items():
            if sid in out:
                raise JobError(f"job {job_id}: stage {sid} has values under two nodes")
            out[sid] = {"node": node, **(values or {})}
    return out


def _size(text: Any) -> tuple[int, int] | None:
    if isinstance(text, str) and "x" in text:
        w, _, h = text.lower().partition("x")
        try:
            return int(w), int(h)
        except ValueError:
            return None
    return None


def _bytes_per_px(fmt: str | None, bitdepth: float | None) -> float:
    fmt = str(fmt or "").upper()
    for key, planes in _BPP.items():
        if fmt.startswith(key):
            return planes * (float(bitdepth or 8) / 8.0)
    if fmt.startswith("RGBA") or fmt.startswith("ARGB"):
        return 4.0
    return float(bitdepth or 8) / 8.0


# --------------------------------------------------------------------------- evaluation

def evaluate_jobs(graph, report: dict[str, Any], inputs, dvfs_tables: dict, config) -> list[dict[str, Any]]:
    """``report.jobs`` of the variant: one entry per selected job (empty when none matches)."""
    raw_jobs = (graph.scenario.pipeline or {}).get("jobs") or []
    if not raw_jobs:
        return []
    vdict = _variant_dict(graph)
    options = getattr(graph.scenario, "power_options", None) or {}
    params = variant_params(options, vdict) if options else {}
    out = []
    for raw in raw_jobs:
        job = JobSpec.model_validate(raw)
        if _selected(job, vdict):
            out.append(_Evaluation(graph, report, inputs, job, _Params(params, f"job {job.id}"), config).run())
    return out


class _Evaluation:
    def __init__(self, graph, report, inputs, job: JobSpec, params: _Params, config):
        self.graph, self.report, self.job, self.p = graph, report, job, params
        self.h_blank = float(getattr(config, "h_blank_margin", 0.0) or 0.0)
        self.period = float(report["period_ms"])
        self.vdict = _variant_dict(graph)
        self.disabled = set((self.vdict["routing_switch"] or {}).get("disabled_nodes") or [])
        self.workloads = {w.node_id: w for w in inputs.workloads}
        self.ips = {ip["node"]: ip for ip in report["ips"]}
        self.ladders = (report.get("dvfs") or {}).get("ladders") or {}
        self.tasks = {str(t["id"]): t for t in inputs.timeline_tasks}
        self.nodes = {str(n.get("id")): n for n in (graph.scenario.pipeline or {}).get("nodes") or []}
        anchors = dict(((graph.scenario.size_profile or {}).get("anchors") or {}))
        anchors.update(graph.variant.size_overrides or {})
        self.anchors = anchors
        self.comp = compression_catalog(getattr(graph, "soc", None), "mean")
        self.notes: list[str] = []
        self.overrides = stage_overrides(graph, job.id)

    # ---- structure
    def _active(self) -> dict[str, JobStage]:
        active = {}
        for s in self.job.stages:
            if not _selected(s, self.vdict):
                continue
            off = [n for n in [*s.nodes, *(s.holds or [])] if n in self.disabled]
            if off:
                self.notes.append(f"stage {s.id} skipped: nodes {off} disabled in this variant")
                continue
            active[s.id] = s
        return active

    @staticmethod
    def _preds(active: dict[str, JobStage]) -> dict[str, list[tuple[str, str]]]:
        """Active predecessors (id, per) after pruning; then the transitive reduction for data flow."""
        preds = {sid: [(a if isinstance(a, str) else a.stage, "stage" if isinstance(a, str) else a.per)
                       for a in (s.after or []) if (a if isinstance(a, str) else a.stage) in active]
                 for sid, s in active.items()}
        return preds

    @staticmethod
    def _ancestors(preds) -> dict[str, set[str]]:
        memo: dict[str, set[str]] = {}

        def anc(sid: str) -> set[str]:
            if sid not in memo:
                memo[sid] = set()
                for p, _ in preds[sid]:
                    memo[sid] |= {p} | anc(p)
            return memo[sid]

        for sid in preds:
            anc(sid)
        return memo

    def _stage_size(self, s: JobStage) -> tuple[int, int]:
        if s.size_ref:
            wh = _size(self.anchors.get(s.size_ref))
            if wh is None:
                raise JobError(f"job {self.job.id}: stage {s.id} size_ref '{s.size_ref}' is not an anchor")
            return wh
        w = self.workloads.get(s.nodes[0])
        if w is not None and w.width and w.height:
            return int(w.width), int(w.height)
        return 0, 0

    def _buffer_mb(self, name: str, size: tuple[int, int], spec: dict[str, Any] | Any) -> float:
        get = spec.get if isinstance(spec, dict) else (lambda k, d=None: getattr(spec, k, d))
        if get("mb") is not None:
            return self.p.num(get("mb"), f"buffers.{name}.mb")
        wh = _size(self.anchors.get(get("size_ref"))) if get("size_ref") else size
        if not wh or not wh[0]:
            return 0.0
        bitdepth = get("bitdepth")
        bd = self.p.num(bitdepth, f"buffers.{name}.bitdepth") if bitdepth is not None else 8.0
        ratio = resolve_comp_ratio(get("compression"), self.comp)
        return wh[0] * wh[1] * _bytes_per_px(get("format"), bd) * ratio / 1e6

    # ---- costs
    def _clock(self, s: JobStage, node: str) -> tuple[float, float]:
        ip = self.ips.get(node) or {}
        group = ip.get("dvfs_group")
        mhz, mv = float(ip.get("set_clock_mhz") or 0.0), float(ip.get("voltage_mv") or 0.0)
        measured = (self.overrides.get(s.id) or {}).get("clock_mhz")
        if measured is not None:
            level = next((lv for lv in self.ladders.get(group, []) if lv["mhz"] >= measured - 1e-6), None)
            return float(measured), float((level or {}).get("mv") or mv)
        if s.clock == "max" and group in self.ladders:
            top = self.ladders[group][-1]
            return float(top["mhz"]), float(top["mv"] or mv)
        if isinstance(s.clock, dict):
            if "dvfs_sn" in s.clock:
                raise JobError(f"job {self.job.id}: stage {s.id} clock dvfs_sn is not supported by {MODEL_ID} yet")
            if group in s.clock:
                want = self.p.num(s.clock[group], f"stages.{s.id}.clock.{group}")
                level = next((lv for lv in self.ladders.get(group, []) if lv["mhz"] >= want - 1e-6), None)
                return want, float((level or {}).get("mv") or mv)
        if mhz <= 0:
            raise JobError(f"job {self.job.id}: stage {s.id} node {node} has no steady clock")
        return mhz, mv

    def _hw_chunk(self, s: JobStage, w: int, h: int, n_chunks: int) -> tuple[float, float, dict[str, float]]:
        px_chunk = w * h / max(1, n_chunks)
        t_max, energy, clocks = 0.0, 0.0, {}
        for node in s.nodes:
            wl = self.workloads.get(node)
            ppc = float((s.ip_params or {}).get("ppc") or (wl.sim_params.ppc if wl else 0.0))
            unit = float((s.ip_params or {}).get("unit_power_mw_mp") or (wl.sim_params.unit_power_mw_mp if wl else 0.0))
            if ppc <= 0:
                raise JobError(f"job {self.job.id}: stage {s.id} node {node} has no ppc (catalog mode or ip_params)")
            mhz, mv = self._clock(s, node)
            clocks[node] = mhz
            t_max = max(t_max, px_chunk / (mhz * 1e6 * ppc) * 1000.0 * (1.0 + self.h_blank))
            energy += calc_active_power_mw(unit_power_mw_mp=unit, resolution_mp=px_chunk / 1e6, voltage_mv=mv or 710.0,
                                           fps=1.0) if unit > 0 else 0.0
        return t_max, energy, clocks

    def _domain_chunk(self, s: JobStage, w: int, h: int, n_chunks: int) -> tuple[float, float, dict[str, float]]:
        node = s.nodes[0]
        ip = self.graph.ip_catalog.get(str(self.nodes[node].get("ip_ref")))
        cfg = domain_load_config(getattr(ip, "capabilities", None) or {}, self.nodes[node],
                                 (self.graph.variant.node_configs or {}).get(node) or {})
        if cfg is None:
            raise JobError(f"job {self.job.id}: stage {s.id} node {node} has no domain load (coefficients)")
        work = s.work or {}
        mcycles = (self.p.num(work["mcycles"], f"stages.{s.id}.work.mcycles") if work.get("mcycles") is not None
                   else self.p.num(work["mcycles_per_mp"], f"stages.{s.id}.work.mcycles_per_mp") * w * h / 1e6)
        freqs = sorted(float(f) for f in (cfg.get("freqs_mhz") or [r["mhz"] for r in cfg.get("vf") or []]))
        f = float((self.overrides.get(s.id) or {}).get("clock_mhz") or cfg.get("freq_mhz") or (freqs[-1] if freqs else 0.0))
        if f <= 0:
            raise JobError(f"job {self.job.id}: stage {s.id} node {node} has no operating point")
        full = {k: v for k, v in cfg.items() if k not in ("mcycles_per_frame", "mcycles_per_layer", "rate_hz",
                                                          "ref_pixels", "pixel_exponent")}
        full.update(mcycles_per_s=f, freq_mhz=f)
        mw = DOMAIN_MODELS[str(cfg["model"])].estimate(node_id=node, cfg=full, rate_hz=0.0, pixels=None)["mw"]
        t = mcycles / max(1, n_chunks) / f * 1000.0
        return t, mw * t / 1000.0, {node: f}

    def _sensor_reservation(self, s: JobStage, frames: float) -> tuple[float, float]:
        mode = self.p.text(s.mode)
        row = self.graph.ip_catalog.get(str(self.nodes[s.nodes[0]].get("ip_ref")))
        modes = ((getattr(row, "capabilities", None) or {}).get("properties") or {}).get("modes") or {}
        fps = float((modes.get(mode) or {}).get("sensor_fps") or (modes.get(mode) or {}).get("fps") or 0.0)
        if fps <= 0:
            raise JobError(f"job {self.job.id}: stage {s.id} sensor mode {mode!r} has no fps in the sensor catalog")
        work = s.work or {}
        t_in = self.p.num(work.get("switch_in_ms", 0), f"stages.{s.id}.work.switch_in_ms")
        t_out = self.p.num(work.get("switch_out_ms", 0), f"stages.{s.id}.work.switch_out_ms")
        readout = frames * 1000.0 / fps
        return t_in + readout, t_in + readout + t_out

    def _resource(self, node: str) -> str:
        task = self.tasks.get(node) or {}
        return str(task.get("resource_id") or node)

    # ---- run
    def run(self) -> dict[str, Any]:
        import simpy

        active = self._active()
        if not active:
            return {"id": self.job.id, "model": MODEL_ID, "stages": [], "notes": self.notes + ["no active stage"]}
        for sid, ov in self.overrides.items():
            if sid not in {s.id for s in self.job.stages}:
                raise JobError(f"job {self.job.id}: node_configs.{ov['node']}.sim.jobs names unknown stage '{sid}'")
            unknown = sorted(set(ov) - OVERRIDE_FIELDS - {"node"})
            if unknown:
                raise JobError(f"job {self.job.id}: stage {sid} values {unknown} are not {sorted(OVERRIDE_FIELDS)}")
            stage = next(s for s in self.job.stages if s.id == sid)
            if ov["node"] not in stage.nodes:
                raise JobError(f"job {self.job.id}: stage {sid} values belong under one of its nodes {stage.nodes}")
            if stage.kind == "sensor" and ("clock_mhz" in ov or "mb" in ov):
                raise JobError(f"job {self.job.id}: sensor stage {sid} takes only service_ms")
            for key in ("service_ms", "clock_mhz", "mb"):
                if key in ov and not (isinstance(ov[key], (int, float)) and not isinstance(ov[key], bool)
                                      and math.isfinite(ov[key]) and ov[key] > 0):
                    raise JobError(f"job {self.job.id}: stage {sid} {key} must be a positive number")
        preds = self._preds(active)
        anc = self._ancestors(preds)
        direct = {sid: [(p, per) for p, per in preds[sid] if not any(p in anc[q] for q, _ in preds[sid] if q != p)]
                  for sid in active}
        buffers = self.job.buffers or {}
        session = (self.graph.scenario.pipeline or {}).get("buffers") or {}

        plan: dict[str, dict[str, Any]] = {}
        for sid, s in active.items():
            w, h = self._stage_size(s)
            frames = max(1, int(round(self.p.num(s.frames, f"stages.{sid}.frames"))))
            passes = max(1, int(round(self.p.num(s.passes, f"stages.{sid}.passes"))))
            per = 1
            if s.chunk is not None and s.chunk.by == "stripe" and s.chunk.max_line_px is not None:
                line = self.p.num(s.chunk.max_line_px, f"stages.{sid}.chunk.max_line_px")
                overlap = self.p.num(s.chunk.overlap_px, f"stages.{sid}.chunk.overlap_px")
                per = max(1, math.ceil(w / max(1.0, line - overlap)))
                w = int(w + overlap * (per - 1))
            elif s.chunk is not None and s.chunk.by == "tile" and s.chunk.tiles is not None:
                per = max(1, int(self.p.num(s.chunk.tiles, f"stages.{sid}.chunk.tiles")))
            setup = (self.p.num(s.chunk.setup_us, f"stages.{sid}.chunk.setup_us") / 1000.0) if s.chunk else 0.0
            entry: dict[str, Any] = {"stage": s, "frames": frames, "passes": passes, "per": per, "w": w, "h": h,
                                     "clocks": {}, "power_mw": 0.0, "attributed": True}
            work = s.work or {}
            if s.kind == "hw":
                t, e, clocks = self._hw_chunk(s, w, h, per)
                entry.update(chunk_ms=t + setup, chunk_mj=e, clocks=clocks)
            elif s.kind == "domain":
                t, e, clocks = self._domain_chunk(s, w, h, per)
                entry.update(chunk_ms=t + setup, chunk_mj=e, clocks=clocks)
            elif s.kind == "sensor":
                ready, total = self._sensor_reservation(s, frames)
                entry.update(chunk_ms=total, chunk_mj=0.0, ready_ms=ready, frames_total=frames, per=1)
            else:
                if s.kind == "sw":
                    t = self.p.num(work["runtime_ms"], f"stages.{sid}.work.runtime_ms")
                elif s.kind == "transfer":
                    t = self.p.num(work["mb"], f"stages.{sid}.work.mb") / self.p.num(
                        work["mb_per_s"], f"stages.{sid}.work.mb_per_s") * 1000.0
                else:
                    t = self.p.num(work["duration_ms"], f"stages.{sid}.work.duration_ms")
                pw = work.get("power_mw")
                mw = self.p.num(pw, f"stages.{sid}.work.power_mw") if pw is not None else 0.0
                entry.update(chunk_ms=t, chunk_mj=mw * t / 1000.0, attributed=pw is not None)
            # bytes per frame: written job buffers + consumed predecessor buffers + session reads
            written = {b: self._buffer_mb(b, (w, h), buffers[b]) for b in (s.writes or [])}
            entry["written"] = written
            entry["session_mb"] = sum(self._buffer_mb(b, (w, h), session[b]) for b in (s.reads or []))
            plan[sid] = entry
        # consumption: buffers from direct predecessors plus `to`
        consumers: dict[str, list[str]] = {}
        for sid in active:
            for p, _ in direct[sid]:
                for b in active[p].writes or []:
                    if not (buffers[b].to):
                        consumers.setdefault(b, []).append(sid)
        for b, spec in buffers.items():
            for t in spec.to or []:
                if t in active:
                    consumers.setdefault(b, []).append(t)
        for sid, e in plan.items():
            e["read_mb"] = sum(plan[p]["written"].get(b, 0.0) for p, _ in direct[sid] for b in active[p].writes or []
                               if sid in consumers.get(b, [])) + e["session_mb"]
            e["write_mb"] = sum(e["written"].values())
            if e["stage"].kind == "sensor":
                e["chunks"] = 1
            else:
                e["chunks"] = e["frames"] * e["passes"] * e["per"]
            self._apply_override(sid, e)

        # ---- SimPy run
        env = simpy.Environment()
        resources: dict[str, Any] = {}

        def res(rid: str):
            if rid not in resources:
                resources[rid] = simpy.PriorityResource(env, capacity=1)
            return resources[rid]

        reserved: dict[str, int] = {}
        bg_prio = 0 if self.job.preview_priority == "rt" else 1
        rt_wait = [0.0]
        dropped = [0]
        stop = env.event()
        bg = [(self._resource(n), float(ip["hw_ms"])) for n, ip in self.ips.items()
              if ip.get("hw_ms") and n in self.tasks and not self.tasks[n].get("independent_period_ms")]

        def background(rid: str, hw_ms: float):
            k = 0
            while not stop.triggered:
                release = k * self.period
                if env.now < release:
                    yield env.timeout(release - env.now)
                if stop.triggered:
                    return
                if reserved.get(rid):
                    dropped[0] += 1
                else:
                    with res(rid).request(priority=bg_prio) as req:
                        yield req
                        rt_wait[0] = max(rt_wait[0], env.now - release)
                        yield env.timeout(hw_ms)
                k += 1

        for rid, hw_ms in bg:
            if self.job.background == "steady":
                env.process(background(rid, hw_ms))

        at = float(self.job.trigger.at_ms)
        done = {sid: env.event() for sid in active}
        frame_done = {sid: [env.event() for _ in range(max(1, plan[sid]["frames"]))] for sid in active}
        ready_evt = {sid: env.event() for sid in active}     # data ready (sensor: end of readout)
        pools = {b: simpy.Container(env, init=int(self.p.num(spec.count, f"buffers.{b}.count")),
                                    capacity=10**6) for b, spec in buffers.items()}
        log: list[dict[str, Any]] = []
        allocs: list[tuple[float, float | None, float, str]] = []   # start, end (None = open), MB, buffer
        open_allocs: dict[tuple[str, int], int] = {}

        def stage_proc(sid: str):
            e, s = plan[sid], active[sid]
            yield env.timeout(at)
            for p, per in preds[sid]:
                if per == "stage":
                    yield ready_evt[p]
            rids = sorted({self._resource(n) for n in [*s.nodes, *(s.holds or [])]})
            start = None
            if s.kind == "sensor":
                reqs = [res(r).request(priority=0) for r in rids]
                for r in reqs:
                    yield r
                start = env.now
                for r in rids:
                    reserved[r] = reserved.get(r, 0) + 1
                for b in s.writes or []:
                    yield pools[b].get(1)
                    open_allocs[(b, 0)] = len(allocs)
                    allocs.append((env.now, None, e["written"][b], b))
                yield env.timeout(e["ready_ms"])
                ready_evt[sid].succeed()
                for ev in frame_done[sid]:
                    ev.succeed()
                yield env.timeout(e["chunk_ms"] - e["ready_ms"])
                for r in rids:
                    reserved[r] -= 1
                for r, rq in zip(rids, reqs):
                    res(r).release(rq)
                log.append({"stage": sid, "start": start, "end": env.now, "mw": 0.0, "mb": e["write_mb"]})
                done[sid].succeed()
                return
            chunks_per_frame = e["passes"] * e["per"]
            for f in range(e["frames"]):
                for p, per in preds[sid]:
                    if per == "frame":
                        idx = min(f, len(frame_done[p]) - 1)
                        yield frame_done[p][idx]
                for b in s.writes or []:
                    yield pools[b].get(1)
                    open_allocs[(b, f)] = len(allocs)
                    allocs.append((env.now, None, e["written"][b], b))
                for _c in range(chunks_per_frame):
                    reqs = [res(r).request(priority=1) for r in rids]
                    for rq in reqs:
                        yield rq
                    t0 = env.now
                    start = t0 if start is None else start
                    yield env.timeout(e["chunk_ms"])
                    for r, rq in zip(rids, reqs):
                        res(r).release(rq)
                    log.append({"stage": sid, "start": t0, "end": env.now,
                                "mw": e["chunk_mj"] / e["chunk_ms"] * 1000.0 if e["chunk_ms"] > 0 else 0.0,
                                "mb": (e["read_mb"] + e["write_mb"]) / chunks_per_frame})
                frame_done[sid][f].succeed()
                # this stage consumed frame f of its per-frame predecessors' pools
                for p, per in preds[sid]:
                    if per == "frame":
                        for b in active[p].writes or []:
                            if sid in consumers.get(b, []):
                                yield pools[b].put(1)
                                i = open_allocs.pop((b, f), None)
                                if i is not None:
                                    allocs[i] = (allocs[i][0], env.now, allocs[i][2], b)
            if not ready_evt[sid].triggered:
                ready_evt[sid].succeed()
            done[sid].succeed()
            # stage-level consumers free whole predecessor buffers at their end
            for p, per in preds[sid]:
                if per == "stage":
                    for b in active[p].writes or []:
                        if sid in consumers.get(b, []):
                            for key in [k for k in open_allocs if k[0] == b]:
                                i = open_allocs.pop(key)
                                allocs[i] = (allocs[i][0], env.now, allocs[i][2], b)
                            yield pools[b].put(max(0, int(self.p.num(buffers[b].count, "count")) - pools[b].level))

        for sid, e in plan.items():
            if e["stage"].kind != "sensor":
                for p, per in preds[sid]:
                    if per == "stage" and plan[p]["stage"].kind != "sensor":
                        for b in active[p].writes or []:
                            cnt = int(self.p.num(buffers[b].count, f"buffers.{b}.count"))
                            if sid in consumers.get(b, []) and cnt < plan[p]["frames"]:
                                raise JobError(f"job {self.job.id}: buffer {b} pool {cnt} < {plan[p]['frames']} "
                                               f"frames of {p}, but {sid} consumes it only after the whole stage "
                                               "(use after: {stage, per: frame})")
            env.process(stage_proc(sid))

        def stopper():
            yield simpy.events.AllOf(env, list(done.values()))
            stop.succeed()

        env.process(stopper())
        horizon = at + 60_000.0
        env.run(until=simpy.events.AnyOf(env, [stop, env.timeout(horizon)]))
        if not stop.triggered:
            raise JobError(f"job {self.job.id}: did not finish within {horizon:.0f} ms (buffer pool deadlock?)")
        end = env.now
        return self._metrics(active, plan, log, allocs, at, end, rt_wait[0], dropped[0], session)

    def _apply_override(self, sid: str, e: dict[str, Any]) -> None:
        """Measured stage values replace the computed ones: ``service_ms`` is the uncontended stage time (split
        evenly over its chunks; constant-power stages keep their power, HW keeps its per-pixel energy), ``mb`` the
        stage traffic (read / write split kept)."""
        ov = self.overrides.get(sid)
        e["value_source"] = e["stage"].value_source
        if not ov:
            return
        e["value_source"] = ov.get("value_source", "measured")
        e["evidence_ref"] = ov.get("evidence_ref")
        if "service_ms" in ov:
            kind = e["stage"].kind
            if kind == "sensor":
                scale = ov["service_ms"] / e["chunk_ms"] if e["chunk_ms"] > 0 else 0.0
                e["ready_ms"], e["chunk_ms"] = e["ready_ms"] * scale, float(ov["service_ms"])
            else:
                new = float(ov["service_ms"]) / e["chunks"]
                if kind != "hw" and e["chunk_ms"] > 0:
                    e["chunk_mj"] *= new / e["chunk_ms"]
                e["chunk_ms"] = new
        if "mb" in ov:
            per_frame = float(ov["mb"]) / max(1, e["frames"])
            total = e["read_mb"] + e["write_mb"]
            share = e["read_mb"] / total if total > 0 else 0.5
            e["read_mb"], e["write_mb"] = per_frame * share, per_frame * (1 - share)

    def _metrics(self, active, plan, log, allocs, at, end, rt_wait, dropped, session) -> dict[str, Any]:
        stages = []
        for sid, e in plan.items():
            rows = [r for r in log if r["stage"] == sid]
            start = min(r["start"] for r in rows) - at
            stop = max(r["end"] for r in rows) - at
            service = sum(r["end"] - r["start"] for r in rows)
            stages.append({
                "id": sid, "phase": e["stage"].phase, "kind": e["stage"].kind, "nodes": list(e["stage"].nodes),
                "chunks": e["chunks"], "start_ms": round(start, 3), "end_ms": round(stop, 3),
                "service_ms": round(service, 3), "elapsed_ms": round(stop - start, 3),
                "clock_mhz": {k: round(v, 1) for k, v in e["clocks"].items()},
                "energy_mj": round(e["chunk_mj"] * (e["chunks"] if e["stage"].kind != "sensor" else 0), 3),
                "mb": round((e["read_mb"] + e["write_mb"]) * e["frames"] * (0 if e["stage"].kind == "sensor" else 1)
                            + (e["write_mb"] if e["stage"].kind == "sensor" else 0.0), 3),
                "energy_attributed": e["attributed"], "value_source": e["value_source"],
                **({"evidence_ref": e["evidence_ref"]} if e.get("evidence_ref") else {}),
            })
        by_kind: dict[str, float] = {}
        for st in stages:
            by_kind[st["kind"]] = round(by_kind.get(st["kind"], 0.0) + st["energy_mj"], 3)
        p_bg = float((self.report.get("power") or {}).get("total_mw") or 0.0)
        bw_bg = float((self.report.get("bw") or {}).get("total_mbs") or 0.0)
        n = int(math.ceil((end - at) / SERIES_DT_MS)) + 1
        times = [at + i * SERIES_DT_MS for i in range(n)]

        def at_t(t: float, key: str) -> float:
            v = 0.0
            for r in log:
                if r["start"] <= t < r["end"] and r["end"] > r["start"]:
                    v += r["mw"] if key == "mw" else r["mb"] / (r["end"] - r["start"]) * 1000.0
            return v

        p_series = [p_bg + at_t(t, "mw") for t in times]
        bw_series = [bw_bg + at_t(t, "mb") for t in times]
        session_mb = 0.0
        for name, spec in session.items():
            if isinstance(spec, dict) and spec.get("lifetime") == "session":
                count = self.p.num(spec.get("count", 1), f"pipeline.buffers.{name}.count")
                wh = _size(self.anchors.get(spec.get("size_ref") or spec.get("size_role")))
                if wh:
                    session_mb += count * self._buffer_mb(name, wh, spec)
        fp_series = [session_mb + sum(mb for s0, s1, mb, _ in allocs if s0 <= t < (s1 if s1 is not None else end + 1))
                     for t in times]

        def window_peak(vals: list[float]) -> float:
            k = max(1, int(PEAK_WINDOW_MS / SERIES_DT_MS))
            if len(vals) <= k:
                return sum(vals) / len(vals)
            acc = sum(vals[:k])
            best = acc
            for i in range(k, len(vals)):
                acc += vals[i] - vals[i - k]
                best = max(best, acc)
            return best / k

        milestones = {}
        for name, sid in (self.job.milestones or {}).items():
            row = next((st for st in stages if st["id"] == sid), None)
            milestones[name] = row["end_ms"] if row else None
        down = max(1, int(1.0 / SERIES_DT_MS))
        return {
            "id": self.job.id, "model": MODEL_ID, "label": self.job.label,
            "params": {k: v for k, v in sorted(self.p.params.items())},
            "milestones": milestones,
            "makespan_ms": round(end - at, 3),
            "phases": [{"id": ph, "start_ms": min(st["start_ms"] for st in stages if st["phase"] == ph),
                        "end_ms": max(st["end_ms"] for st in stages if st["phase"] == ph)}
                       for ph in (self.job.phases or sorted({st["phase"] for st in stages}))
                       if any(st["phase"] == ph for st in stages)],
            "stages": stages,
            "energy_mj": {"event": round(sum(by_kind.values()), 3), "by_kind": by_kind,
                          "unattributed": sorted(st["id"] for st in stages if not st["energy_attributed"])},
            "peak": {"window_ms": PEAK_WINDOW_MS, "power_mw": round(window_peak(p_series), 1),
                     "power_instant_mw": round(max(p_series), 1), "bw_mbs": round(window_peak(bw_series), 1),
                     "bw_instant_mbs": round(max(bw_series), 1), "footprint_mb": round(max(fp_series), 3)},
            "background": {"power_mw": round(p_bg, 3), "bw_mbs": round(bw_bg, 3), "rt_wait_max_ms": round(rt_wait, 3),
                           "dropped_frames": dropped, "priority": self.job.preview_priority},
            "series": {"dt_ms": SERIES_DT_MS * down, "power_mw": [round(v, 1) for v in p_series[::down]],
                       "bw_mbs": [round(v, 1) for v in bw_series[::down]],
                       "footprint_mb": [round(v, 2) for v in fp_series[::down]]},
            "basis": ("job-v1: background = per-resource steady HW occupancy at RT priority; HW energy = v1 dynamic "
                      "term at fps 1 (static / clock terms not attributed); constant steady power / BW underneath."),
            "notes": self.notes,
        }
