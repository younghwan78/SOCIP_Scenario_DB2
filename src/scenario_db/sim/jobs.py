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
from scenario_db.models.definition.job import AfterRef, JobSpec, JobStage, range_error
from scenario_db.sim.bw_calc import resolve_comp_ratio
from scenario_db.sim.domain_loads import DOMAIN_MODELS, domain_load_config
from scenario_db.sim.power_calc import calc_active_power_mw
from scenario_db.sim.timeline_adapter import own_cadence
from scenario_db.sim.transfers import compression_catalog

MODEL_ID = "job-v1"
PEAK_WINDOW_MS = 10.0
MAX_CHUNKS = 20_000          # one job's chunks (frames x passes x stripes / tiles over its stages)
MAX_AT_MS = 60_000.0         # trigger time (the background runs from 0)
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
            return float(value)                  # literals are range-checked by the schema
        try:
            out = eval_expr(value, self.params)
        except KnobError as exc:
            raise JobError(f"{self.where}.{path}: {exc}") from None
        if not math.isfinite(out):
            raise JobError(f"{self.where}.{path}: {value!r} = {out} is not a finite number")
        if path.split(".")[0] in ("stages", "buffers", "trigger"):   # job fields: the schema literal ranges
            problem = range_error(path, out)
            if problem:
                raise JobError(f"{self.where}: {problem} ({value!r})")
        return out

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
        if not isinstance(jobs, dict) or not isinstance(jobs.get(job_id) or {}, dict):
            raise JobError(f"job {job_id}: node_configs.{node}.sim.jobs must map job -> stage -> values")
        for sid, values in (jobs.get(job_id) or {}).items():
            if not isinstance(values, dict):
                raise JobError(f"job {job_id}: node_configs.{node}.sim.jobs.{job_id}.{sid} must be a mapping")
            if sid in out:
                raise JobError(f"job {job_id}: stage {sid} has values under two nodes")
            out[sid] = {"node": node, **values}
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

def job_inputs(graph) -> tuple[dict[str, Any], dict[str, Any]]:
    """What job selection and parameters depend on: the variant fields and its resolved knob params."""
    vdict = _variant_dict(graph)
    options = getattr(graph.scenario, "power_options", None) or {}
    return vdict, (variant_params(options, vdict) if options else {})


def evaluate_jobs(graph, report: dict[str, Any], inputs, dvfs_tables: dict, config) -> list[dict[str, Any]]:
    """``report.jobs`` of the variant: one entry per selected job (empty when none matches)."""
    raw_jobs = (graph.scenario.pipeline or {}).get("jobs") or []
    if not raw_jobs:
        return []
    vdict, params = job_inputs(graph)
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

    def _sensor_mode(self, s: JobStage) -> dict[str, Any]:
        mode = self.p.text(s.mode)
        row = self.graph.ip_catalog.get(str(self.nodes[s.nodes[0]].get("ip_ref")))
        modes = ((getattr(row, "capabilities", None) or {}).get("properties") or {}).get("modes") or {}
        if not isinstance(modes.get(mode), dict):
            raise JobError(f"job {self.job.id}: stage {s.id} sensor mode {mode!r} is not in the sensor catalog")
        return modes[mode]

    def _stage_size(self, s: JobStage) -> tuple[int, int]:
        if s.kind == "sensor" and not s.size_ref:          # the selected readout mode
            size = self._sensor_mode(s).get("sensor_size") or []
            if len(size) == 2:
                return int(size[0]), int(size[1])
        if s.size_ref:
            wh = _size(self.anchors.get(s.size_ref))
            if wh is None:
                raise JobError(f"job {self.job.id}: stage {s.id} size_ref '{s.size_ref}' is not an anchor")
            return wh
        w = self.workloads.get(s.nodes[0])
        if w is not None and w.width and w.height:
            return int(w.width), int(w.height)
        return 0, 0

    def _buffer_mb(self, name: str, size: tuple[int, int], spec: dict[str, Any] | Any, required: bool = False) -> float:
        get = spec.get if isinstance(spec, dict) else (lambda k, d=None: getattr(spec, k, d))
        if get("mb") is not None:
            return self.p.num(get("mb"), f"buffers.{name}.mb")
        wh = _size(self.anchors.get(get("size_ref"))) if get("size_ref") else size
        if not wh or not wh[0]:
            if required:
                raise JobError(f"job {self.job.id}: buffer {name} has no size (declare mb or size_ref, or write it "
                               "from a stage with a size)")
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
        mode = self.p.text(s.mode) if s.mode is not None else None
        for node in s.nodes:
            wl = self.workloads.get(node)
            base_ppc = float(wl.sim_params.ppc if wl else 0.0)
            base_unit = float(wl.sim_params.unit_power_mw_mp if wl else 0.0)
            if mode is not None:                      # the stage's catalog sim mode replaces the session mode
                row = self.graph.ip_catalog.get(str(self.nodes[node].get("ip_ref")))
                modes = ((getattr(row, "capabilities", None) or {}).get("sim") or {}).get("modes") or {}
                if mode not in modes:
                    raise JobError(f"job {self.job.id}: stage {s.id} node {node} has no catalog mode {mode!r} "
                                   f"(modes {sorted(modes)})")
                base_ppc = float(modes[mode].get("ppc") or 0.0)
                base_unit = float(modes[mode].get("unit_power_mw_mp") or 0.0)
            ipp = s.ip_params or {}
            ppc = (self.p.num(ipp["ppc"], f"stages.{s.id}.ip_params.ppc") if ipp.get("ppc") is not None
                   else base_ppc)
            unit = (self.p.num(ipp["unit_power_mw_mp"], f"stages.{s.id}.ip_params.unit_power_mw_mp")
                    if ipp.get("unit_power_mw_mp") is not None else base_unit)
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

    def _sensor_reservation(self, s: JobStage) -> tuple[float, float, float]:
        """(switch-in, one frame readout, switch-out) in ms."""
        mode = self._sensor_mode(s)
        fps = float(mode.get("sensor_fps") or mode.get("fps") or 0.0)
        if fps <= 0:
            raise JobError(f"job {self.job.id}: stage {s.id} sensor mode {self.p.text(s.mode)!r} has no fps")
        work = s.work or {}
        t_in = self.p.num(work.get("switch_in_ms", 0), f"stages.{s.id}.work.switch_in_ms")
        t_out = self.p.num(work.get("switch_out_ms", 0), f"stages.{s.id}.work.switch_out_ms")
        return t_in, 1000.0 / fps, t_out

    def _resource(self, node: str) -> str:
        task = self.tasks.get(node) or {}
        return str(task.get("resource_id") or node)

    # ---- run
    def _check_overrides(self) -> None:
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

    def _plan_stage(self, sid: str, s: JobStage, buffers, session) -> dict[str, Any]:
        w, h = self._stage_size(s)
        frames = int(self.p.num(s.frames, f"stages.{sid}.frames"))
        passes = int(self.p.num(s.passes, f"stages.{sid}.passes"))
        per, w_proc = 1, w
        if s.chunk is not None and s.chunk.by == "stripe" and s.chunk.max_line_px is not None:
            line = self.p.num(s.chunk.max_line_px, f"stages.{sid}.chunk.max_line_px")
            overlap = self.p.num(s.chunk.overlap_px, f"stages.{sid}.chunk.overlap_px")
            if line <= overlap:
                raise JobError(f"job {self.job.id}: stage {sid} chunk.max_line_px {line} must exceed overlap_px "
                               f"{overlap}")
            per = max(1, math.ceil(w / (line - overlap)))
            w_proc = int(w + overlap * (per - 1))          # overlap is processed twice, not stored twice
        elif s.chunk is not None and s.chunk.by == "tile" and s.chunk.tiles is not None:
            per = int(self.p.num(s.chunk.tiles, f"stages.{sid}.chunk.tiles"))
        setup = (self.p.num(s.chunk.setup_us, f"stages.{sid}.chunk.setup_us") / 1000.0) if s.chunk else 0.0
        e: dict[str, Any] = {"stage": s, "frames": frames, "passes": passes, "per": per, "w": w, "h": h,
                             "clocks": {}, "attributed": True, "xfer_mb": 0.0}
        work = s.work or {}
        if s.kind == "hw":
            t, mj, clocks = self._hw_chunk(s, w_proc, h, per)
            e.update(chunk_ms=t + setup, chunk_mj=mj, clocks=clocks)
        elif s.kind == "domain":
            t, mj, clocks = self._domain_chunk(s, w_proc, h, per)
            e.update(chunk_ms=t + setup, chunk_mj=mj, clocks=clocks)
        elif s.kind == "sensor":
            t_in, frame_ms, t_out = self._sensor_reservation(s)
            # no sensor power model yet: its energy is not attributed
            e.update(t_in=t_in, frame_ms=frame_ms, t_out=t_out, chunk_ms=t_in + frames * frame_ms + t_out,
                     chunk_mj=0.0, attributed=False, per=1, passes=1)
        else:
            if s.kind == "sw":
                t = self.p.num(work["runtime_ms"], f"stages.{sid}.work.runtime_ms")
            elif s.kind == "transfer":
                e["xfer_mb"] = self.p.num(work["mb"], f"stages.{sid}.work.mb")
                t = e["xfer_mb"] / self.p.num(work["mb_per_s"], f"stages.{sid}.work.mb_per_s") * 1000.0
            else:
                t = self.p.num(work["duration_ms"], f"stages.{sid}.work.duration_ms")
            pw = work.get("power_mw")
            mw = self.p.num(pw, f"stages.{sid}.work.power_mw") if pw is not None else 0.0
            e.update(chunk_ms=t, chunk_mj=mw * t / 1000.0, attributed=pw is not None)
        e["written"] = {b: self._buffer_mb(b, (w, h), buffers[b], required=True) for b in (s.writes or [])}
        e["session_mb"] = sum(self._buffer_mb(b, (w, h), session[b]) for b in (s.reads or []))
        return e

    def run(self) -> dict[str, Any]:
        import simpy

        if self.job.trigger.kind != "event":
            raise JobError(f"job {self.job.id}: trigger kind {self.job.trigger.kind!r} is not supported by "
                           f"{MODEL_ID} (event only)")
        active = self._active()
        if not active:
            return {"id": self.job.id, "model": MODEL_ID, "stages": [], "notes": self.notes + ["no active stage"]}
        self._check_overrides()
        at = self.p.num(self.job.trigger.at_ms, "trigger.at_ms")
        if at > MAX_AT_MS:
            raise JobError(f"job {self.job.id}: trigger.at_ms {at} exceeds {MAX_AT_MS:.0f} ms")
        preds = self._preds(active)
        anc = self._ancestors(preds)
        direct = {sid: [(p, per) for p, per in preds[sid] if not any(p in anc[q] for q, _ in preds[sid] if q != p)]
                  for sid in active}
        buffers = self.job.buffers or {}
        session = (self.graph.scenario.pipeline or {}).get("buffers") or {}

        producer: dict[str, str] = {}
        for sid, s in active.items():
            for b in s.writes or []:
                if b in producer:
                    raise JobError(f"job {self.job.id}: buffer {b} is written by {producer[b]} and {sid}")
                producer[b] = sid
        # consumers: the direct successors of the producer, or the stages its `to` names (explicit)
        consumers: dict[str, list[str]] = {b: [] for b in producer}
        for sid in active:
            for p, _ in direct[sid]:
                for b in active[p].writes or []:
                    if not buffers[b].to and sid not in consumers[b]:
                        consumers[b].append(sid)
        for b in producer:
            for t in buffers[b].to or []:
                if t in active and t not in consumers[b]:
                    consumers[b].append(t)
        # what each stage waits for: its `after` stages, and the producers of buffers it consumes (stage level
        # unless the `after` names that producer per frame)
        waits: dict[str, list[tuple[str, str]]] = {sid: list(preds[sid]) for sid in active}
        inputs: dict[str, list[tuple[str, str]]] = {sid: [] for sid in active}      # (buffer, per)
        for b, cs in consumers.items():
            for c in cs:
                per = "frame" if (producer[b], "frame") in preds[c] else "stage"
                inputs[c].append((b, per))
                if not any(p == producer[b] for p, _ in waits[c]):
                    waits[c].append((producer[b], "stage"))

        plan = {sid: self._plan_stage(sid, s, buffers, session) for sid, s in active.items()}
        total = 0
        for sid, e in plan.items():
            e["read_mb"] = sum(plan[producer[b]]["written"][b] for b, _ in inputs[sid]) + e["session_mb"]
            e["write_mb"] = sum(e["written"].values())
            if e["xfer_mb"] and not (e["read_mb"] or e["write_mb"]):
                e["write_mb"] = e["xfer_mb"] * e["passes"] * e["per"]     # declared transfer, no buffer for it
            e["chunks"] = 1 if e["stage"].kind == "sensor" else e["frames"] * e["passes"] * e["per"]
            total += e["frames"] * e["passes"] * e["per"]
            self._apply_override(sid, e)
            for p, per in preds[sid]:
                if per == "frame" and e["frames"] > plan[p]["frames"]:
                    raise JobError(f"job {self.job.id}: stage {sid} has {e['frames']} frames per-frame after {p} "
                                   f"with {plan[p]['frames']}")
        if total > MAX_CHUNKS:
            raise JobError(f"job {self.job.id}: {total} chunks exceed {MAX_CHUNKS} (frames x passes x stripes)")
        counts = {b: int(self.p.num(buffers[b].count, f"buffers.{b}.count")) for b in producer}
        for b, cs in consumers.items():
            for c in cs:
                if (b, "stage") in inputs[c] and counts[b] < plan[producer[b]]["frames"]:
                    raise JobError(f"job {self.job.id}: buffer {b} pool {counts[b]} < {plan[producer[b]]['frames']} "
                                   f"frames of {producer[b]}, but {c} consumes it only after the whole stage "
                                   "(use after: {stage, per: frame})")

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
        # frame-DAG HW only: own-cadence tasks (period / divided / event / vsync) are not released every frame
        bg = [(self._resource(n), float(ip["hw_ms"])) for n, ip in self.ips.items()
              if ip.get("hw_ms") and n in self.tasks and not own_cadence(self.tasks[n])]

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

        if self.job.background == "steady":
            for rid, hw_ms in bg:
                env.process(background(rid, hw_ms))

        done = {sid: env.event() for sid in active}
        frame_done = {sid: [env.event() for _ in range(plan[sid]["frames"])] for sid in active}
        ready_evt = {sid: env.event() for sid in active}     # data ready (sensor: end of readout)
        pools = {b: simpy.Container(env, init=counts[b], capacity=10**6) for b in producer}
        log: list[dict[str, Any]] = []
        allocs: list[tuple[float, float | None, float, str]] = []   # start, end (None = open), MB, buffer
        open_allocs: dict[tuple[str, int], int] = {}
        pending: dict[tuple[str, int], set[str]] = {}               # consumers still reading frame f of b

        def produce(b: str, f: int, mb: float) -> None:
            open_allocs[(b, f)] = len(allocs)
            allocs.append((env.now, None, mb, b))
            pending[(b, f)] = set(consumers[b])

        def consume(b: str, f: int, sid: str) -> bool:
            """``sid`` is done with frame f of b; True when it was the last reader (the slot is free)."""
            left = pending.get((b, f))
            if left is None or sid not in left:
                return False
            left.discard(sid)
            if left:
                return False
            del pending[(b, f)]
            i = open_allocs.pop((b, f))
            allocs[i] = (allocs[i][0], env.now, allocs[i][2], b)
            return True

        def acquire(rids: list[str], prio: int):
            # one global order (sorted ids): a stage holding several resources can never wait in a cycle
            reqs = []
            for r in rids:
                rq = res(r).request(priority=prio)
                yield rq
                reqs.append(rq)
            return reqs

        def stage_proc(sid: str):
            e, s = plan[sid], active[sid]
            yield env.timeout(at)
            for p, per in waits[sid]:
                if per == "stage":
                    yield ready_evt[p]
            rids = sorted({self._resource(n) for n in [*s.nodes, *(s.holds or [])]})
            if s.kind == "sensor":
                reqs = yield from acquire(rids, 0)
                start = env.now
                for r in rids:
                    reserved[r] = reserved.get(r, 0) + 1
                yield env.timeout(e["t_in"])
                for f in range(e["frames"]):
                    for b in s.writes or []:
                        yield pools[b].get(1)
                        produce(b, f, e["written"][b])
                    yield env.timeout(e["frame_ms"])
                    frame_done[sid][f].succeed()
                ready_evt[sid].succeed()
                yield env.timeout(e["t_out"])
                for r in rids:
                    reserved[r] -= 1
                for r, rq in zip(rids, reqs):
                    res(r).release(rq)
                log.append({"stage": sid, "start": start, "end": env.now, "mw": 0.0, "mb": e["write_mb"] * e["frames"]})
                done[sid].succeed()
                return
            chunks_per_frame = e["passes"] * e["per"]
            for f in range(e["frames"]):
                for p, per in waits[sid]:
                    if per == "frame":
                        yield frame_done[p][f]
                for b in s.writes or []:
                    yield pools[b].get(1)
                    produce(b, f, e["written"][b])
                for _c in range(chunks_per_frame):
                    reqs = yield from acquire(rids, 1)
                    t0 = env.now
                    yield env.timeout(e["chunk_ms"])
                    for r, rq in zip(rids, reqs):
                        res(r).release(rq)
                    log.append({"stage": sid, "start": t0, "end": env.now,
                                "mw": e["chunk_mj"] / e["chunk_ms"] * 1000.0 if e["chunk_ms"] > 0 else 0.0,
                                "mb": (e["read_mb"] + e["write_mb"]) / chunks_per_frame})
                frame_done[sid][f].succeed()
                for b, per in inputs[sid]:               # frame f of a per-frame input is read
                    if per == "frame" and consume(b, f, sid):
                        yield pools[b].put(1)
            if not ready_evt[sid].triggered:
                ready_evt[sid].succeed()
            done[sid].succeed()
            for b, per in inputs[sid]:                   # stage-level inputs are read once the stage ends
                if per == "stage":
                    for f in range(plan[producer[b]]["frames"]):
                        if consume(b, f, sid):
                            yield pools[b].put(1)

        for sid in plan:
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
        return self._metrics(plan, log, allocs, at, end, rt_wait[0], dropped[0], session)

    def _apply_override(self, sid: str, e: dict[str, Any]) -> None:
        """Measured stage values replace the computed ones: ``service_ms`` is the uncontended stage time (split
        evenly over its chunks; constant-power stages keep their power, HW keeps its per-pixel energy), ``mb`` the
        stage traffic (read / write split kept). Provenance: the stage's own fields, replaced by the slot's."""
        s = e["stage"]
        e["value_source"], e["evidence_ref"], e["basis"] = s.value_source, s.evidence_ref, s.basis
        ov = self.overrides.get(sid)
        if not ov:
            return
        e["value_source"] = ov.get("value_source", "measured")
        e["evidence_ref"] = ov.get("evidence_ref", e["evidence_ref"])
        e["basis"] = ov.get("basis", e["basis"])
        if "service_ms" in ov:
            if s.kind == "sensor":
                scale = ov["service_ms"] / e["chunk_ms"] if e["chunk_ms"] > 0 else 0.0
                e["t_in"], e["frame_ms"], e["t_out"] = (e["t_in"] * scale, e["frame_ms"] * scale, e["t_out"] * scale)
                e["chunk_ms"] = float(ov["service_ms"])
            else:
                new = float(ov["service_ms"]) / e["chunks"]
                if s.kind != "hw" and e["chunk_ms"] > 0:
                    e["chunk_mj"] *= new / e["chunk_ms"]
                e["chunk_ms"] = new
        if "mb" in ov:
            per_frame = float(ov["mb"]) / max(1, e["frames"])
            total = e["read_mb"] + e["write_mb"]
            share = e["read_mb"] / total if total > 0 else 0.5
            e["read_mb"], e["write_mb"] = per_frame * share, per_frame * (1 - share)

    def _metrics(self, plan, log, allocs, at, end, rt_wait, dropped, session) -> dict[str, Any]:
        stages = []
        for sid, e in plan.items():
            rows = [r for r in log if r["stage"] == sid]
            start = min(r["start"] for r in rows) - at
            stop = max(r["end"] for r in rows) - at
            service = sum(r["end"] - r["start"] for r in rows)
            sensor = e["stage"].kind == "sensor"
            stages.append({
                "id": sid, "phase": e["stage"].phase, "kind": e["stage"].kind, "nodes": list(e["stage"].nodes),
                "chunks": e["chunks"], "start_ms": round(start, 3), "end_ms": round(stop, 3),
                "service_ms": round(service, 3), "elapsed_ms": round(stop - start, 3),
                "clock_mhz": {k: round(v, 1) for k, v in e["clocks"].items()},
                "energy_mj": round(0.0 if sensor else e["chunk_mj"] * e["chunks"], 3),
                "mb": round((e["read_mb"] + e["write_mb"]) * e["frames"], 3),
                "energy_attributed": e["attributed"], "value_source": e["value_source"],
                **({"evidence_ref": e["evidence_ref"]} if e.get("evidence_ref") else {}),
                **({"basis": e["basis"]} if e.get("basis") else {}),
            })
        by_kind: dict[str, float] = {}
        for st in stages:
            by_kind[st["kind"]] = round(by_kind.get(st["kind"], 0.0) + st["energy_mj"], 3)
        p_bg = float((self.report.get("power") or {}).get("total_mw") or 0.0)
        bw_bg = float((self.report.get("bw") or {}).get("total_mbs") or 0.0)
        session_mb = 0.0
        for name, spec in session.items():
            if isinstance(spec, dict) and spec.get("lifetime") == "session":
                count = self.p.num(spec.get("count", 1), f"pipeline.buffers.{name}.count")
                wh = _size(self.anchors.get(spec.get("size_ref") or spec.get("size_role")))
                if wh:
                    session_mb += count * self._buffer_mb(name, wh, spec)
        power = _Profile([(r["start"], r["end"], r["mw"]) for r in log if r["end"] > r["start"]])
        bw = _Profile([(r["start"], r["end"], r["mb"] / (r["end"] - r["start"]) * 1000.0)
                       for r in log if r["end"] > r["start"]])
        footprint = _Profile([(s0, s1 if s1 is not None else end + 1.0, mb) for s0, s1, mb, _ in allocs
                              if (s1 if s1 is not None else end + 1.0) > s0])   # open = held to the end
        dt = 1.0
        times = [at + i * dt for i in range(int(math.ceil((end - at) / dt)) + 1)]
        milestones = {}
        for name, sid in (self.job.milestones or {}).items():
            row = next((st for st in stages if st["id"] == sid), None)
            milestones[name] = row["end_ms"] if row else None
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
            # exact over the run intervals: the instant peak, and the best PEAK_WINDOW_MS average with the
            # steady power / BW before and after the job inside the window
            "peak": {"window_ms": PEAK_WINDOW_MS, "power_mw": round(p_bg + power.window_peak(PEAK_WINDOW_MS), 1),
                     "power_instant_mw": round(p_bg + power.peak(), 1),
                     "bw_mbs": round(bw_bg + bw.window_peak(PEAK_WINDOW_MS), 1),
                     "bw_instant_mbs": round(bw_bg + bw.peak(), 1),
                     "footprint_mb": round(session_mb + footprint.peak(), 3)},
            "background": {"power_mw": round(p_bg, 3), "bw_mbs": round(bw_bg, 3), "rt_wait_max_ms": round(rt_wait, 3),
                           "dropped_frames": dropped, "priority": self.job.preview_priority},
            "series": {"dt_ms": dt, "power_mw": [round(p_bg + power.at(t), 1) for t in times],
                       "bw_mbs": [round(bw_bg + bw.at(t), 1) for t in times],
                       "footprint_mb": [round(session_mb + footprint.at(t), 2) for t in times]},
            "basis": ("job-v1: background = per-resource steady HW occupancy at RT priority; HW energy = v1 dynamic "
                      "term at fps 1 (static / clock terms not attributed; sensor energy not modelled); constant "
                      "steady power / BW underneath."),
            "notes": self.notes,
        }


class _Profile:
    """Sum of constant-rate intervals [start, end) -> value, evaluated exactly (no sampling)."""

    def __init__(self, segments: list[tuple[float, float, float]]):
        import bisect

        self._bisect = bisect
        deltas: dict[float, float] = {}
        for s0, s1, v in segments:
            deltas[s0] = deltas.get(s0, 0.0) + v
            deltas[s1] = deltas.get(s1, 0.0) - v
        self.t = sorted(deltas)
        self.rate: list[float] = []          # value on [t[i], t[i+1])
        self.area: list[float] = []          # integral from t[0] to t[i]
        acc, area = 0.0, 0.0
        for i, t in enumerate(self.t):
            if i:
                area += acc * (t - self.t[i - 1])
            self.area.append(area)
            acc += deltas[t]
            self.rate.append(acc)

    def at(self, x: float) -> float:
        i = self._bisect.bisect_right(self.t, x) - 1
        return self.rate[i] if 0 <= i < len(self.rate) else 0.0

    def peak(self) -> float:
        return max(self.rate, default=0.0)

    def _integral(self, x: float) -> float:
        i = self._bisect.bisect_right(self.t, x) - 1
        if i < 0:
            return 0.0
        return self.area[i] + self.rate[i] * (x - self.t[i])

    def window_peak(self, window: float) -> float:
        # the best window starts or ends at a breakpoint (piecewise-constant rate)
        best = 0.0
        for t in self.t:
            for a in (t, t - window):
                best = max(best, (self._integral(a + window) - self._integral(a)) / window)
        return best
