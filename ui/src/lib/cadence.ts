// Frame cadence / latency analysis on a timeline (trace or simulation schedule).
// Answers: does the preview / video buffer period meet the scenario fps, and how
// are the intervals distributed (box plot), plus per-stage frame-relative timing.
import type { ViewResponse } from './api'
import { pipelineIdOf } from './graph'
import type { Slice, Timeline } from './timeline'

export interface BoxStats { n: number; min: number; q1: number; median: number; q3: number; max: number; mean: number; std: number; p95: number }

export function quantile(sorted: number[], q: number): number {
  if (!sorted.length) return NaN
  const pos = (sorted.length - 1) * q
  const lo = Math.floor(pos), hi = Math.ceil(pos)
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo)
}

export function boxStats(values: number[]): BoxStats | null {
  const v = values.filter(Number.isFinite).sort((a, b) => a - b)
  if (!v.length) return null
  const mean = v.reduce((s, x) => s + x, 0) / v.length
  const std = Math.sqrt(v.reduce((s, x) => s + (x - mean) ** 2, 0) / v.length)
  return { n: v.length, min: v[0], q1: quantile(v, 0.25), median: quantile(v, 0.5), q3: quantile(v, 0.75), max: v[v.length - 1], mean, std, p95: quantile(v, 0.95) }
}

const sensorLike = (s: Slice) => (s.nodeId ?? '').startsWith('sensor') || s.group === 'SENSOR'

/** Frame origin = sensor readout start of the frame (fallback: earliest slice of the frame). */
export function frameOrigins(tl: Timeline): Map<number, number> {
  const out = new Map<number, number>()
  const fallback = new Map<number, number>()
  for (const s of tl.slices) {
    if (s.frame === null) continue
    fallback.set(s.frame, Math.min(fallback.get(s.frame) ?? Infinity, s.start))
    if (sensorLike(s)) out.set(s.frame, Math.min(out.get(s.frame) ?? Infinity, s.start))
  }
  for (const [f, t] of fallback) if (!out.has(f)) out.set(f, t)
  return out
}

export interface StageTiming { pid: string; offset: number; dur: number; durMin: number; durMax: number; n: number }

/** Mean frame-relative start offset and duration per pipeline node id. */
export function stageTimings(tl: Timeline): Map<string, StageTiming> {
  const origin = frameOrigins(tl)
  const acc = new Map<string, { off: number[]; dur: number[] }>()
  for (const s of tl.slices) {
    if (!s.nodeId || s.frame === null) continue
    const pid = pipelineIdOf(s.nodeId.replace(/^stage:/, ''))
    const o = origin.get(s.frame)
    if (o === undefined) continue
    const a = acc.get(pid) ?? { off: [], dur: [] }
    a.off.push(s.start - o); a.dur.push(s.end - s.start)
    acc.set(pid, a)
  }
  const out = new Map<string, StageTiming>()
  const mean = (v: number[]) => v.reduce((x, y) => x + y, 0) / v.length
  for (const [pid, a] of acc) out.set(pid, { pid, offset: mean(a.off), dur: mean(a.dur), durMin: Math.min(...a.dur), durMax: Math.max(...a.dur), n: a.dur.length })
  return out
}

export interface Stream { id: string; label: string; pid: string; kind: 'buffer' | 'sink' | 'input'; times: { frame: number; t: number }[] }

/** Producer of the buffer consumed by a sink IP (DPU → preview buffer, MFC → video buffer). */
function feederOf(view: ViewResponse | undefined, sink: RegExp): string | null {
  if (!view) return null
  const e = view.edges.map((x) => x.data).find((x) => x.flow_type === 'M2M' && sink.test(pipelineIdOf(x.target)))
  return e ? pipelineIdOf(e.source) : null
}

export function streamsOf(tl: Timeline, view?: ViewResponse): Stream[] {
  const byPid = new Map<string, Slice[]>()
  for (const s of tl.slices) {
    if (!s.nodeId || s.frame === null) continue
    const pid = pipelineIdOf(s.nodeId.replace(/^stage:/, ''))
    byPid.set(pid, [...(byPid.get(pid) ?? []), s])
  }
  const lastEnd = (pid: string) => {
    const m = new Map<number, number>()
    for (const s of byPid.get(pid) ?? []) m.set(s.frame!, Math.max(m.get(s.frame!) ?? -Infinity, s.end))
    return [...m.entries()].sort((a, b) => a[0] - b[0]).map(([frame, t]) => ({ frame, t }))
  }
  const firstPid = (re: RegExp) => [...byPid.keys()].find((p) => re.test(p)) ?? null
  const out: Stream[] = []
  const prevFeed = feederOf(view, /^dpu|^decon/) ?? firstPid(/^gdc_m$|preview/)
  const vidFeed = feederOf(view, /^mfc|^apv/) ?? firstPid(/^gdc_o$|video/)
  if (prevFeed && byPid.has(prevFeed)) out.push({ id: 'preview', label: `Preview buffer (${prevFeed.toUpperCase()} → DPU)`, pid: prevFeed, kind: 'buffer', times: lastEnd(prevFeed) })
  if (vidFeed && byPid.has(vidFeed)) out.push({ id: 'video', label: `Video buffer (${vidFeed.toUpperCase()} → MFC)`, pid: vidFeed, kind: 'buffer', times: lastEnd(vidFeed) })
  const disp = firstPid(/^panel|^dpu/)
  if (disp) out.push({ id: 'display', label: `Display (${disp.toUpperCase()} done)`, pid: disp, kind: 'sink', times: lastEnd(disp) })
  const enc = firstPid(/^mfc|^apv/)
  if (enc) out.push({ id: 'encode', label: `Encoder (${enc.toUpperCase()} done)`, pid: enc, kind: 'sink', times: lastEnd(enc) })
  const origin = frameOrigins(tl)
  out.push({ id: 'sensor', label: 'Sensor frame start', pid: 'sensor', kind: 'input', times: [...origin.entries()].sort((a, b) => a[0] - b[0]).map(([frame, t]) => ({ frame, t })) })
  return out.filter((s) => s.times.length >= 1)
}

export type Verdict = 'ok' | 'warn' | 'fail' | 'na'

export interface CadenceResult {
  stream: Stream
  intervals: number[]
  latencies: number[]
  box: BoxStats | null
  latBox: BoxStats | null
  fpsAchieved: number | null
  drops: number
  batch: boolean
  verdict: Verdict
}

/** Interval analysis vs target period (1000/fps). Batch = bimodal (bursts of short intervals + long gaps). */
export function analyse(tl: Timeline, view: ViewResponse | undefined, fps: number | null): { period: number | null; results: CadenceResult[]; inFlight: number } {
  const period = fps ? 1000 / fps : null
  const origin = frameOrigins(tl)
  const results = streamsOf(tl, view).map((stream) => {
    const t = stream.times
    const intervals = t.slice(1).map((x, i) => x.t - t[i].t)
    const latencies = stream.kind === 'input' ? [] : t.map((x) => x.t - (origin.get(x.frame) ?? x.t)).filter((x) => x > 0)
    const box = boxStats(intervals)
    const span = t.length > 1 ? t[t.length - 1].t - t[0].t : 0
    const fpsAchieved = span > 0 ? ((t.length - 1) / span) * 1000 : null
    const drops = period ? intervals.filter((x) => x > period * 1.5).length : 0
    const short = period ? intervals.filter((x) => x < period * 0.5).length : 0
    const batch = !!period && short > 0 && drops > 0
    let verdict: Verdict = 'na'
    if (period && fpsAchieved !== null) {
      const ratio = fpsAchieved / (1000 / period)
      verdict = ratio >= 0.995 && (batch || drops === 0) ? (box && box.max > period * 1.2 && !batch ? 'warn' : 'ok') : ratio >= 0.95 ? 'warn' : 'fail'
    }
    return { stream, intervals, latencies, box, latBox: boxStats(latencies), fpsAchieved, drops: batch ? 0 : drops, batch, verdict }
  })
  // pipelining depth: max frames simultaneously in flight
  const spans = new Map<number, [number, number]>()
  for (const s of tl.slices) {
    if (s.frame === null) continue
    const cur = spans.get(s.frame) ?? [Infinity, -Infinity]
    spans.set(s.frame, [Math.min(cur[0], s.start), Math.max(cur[1], s.end)])
  }
  const evts = [...spans.values()].flatMap(([a, b]) => [[a, 1], [b, -1]] as [number, number][]).sort((x, y) => x[0] - y[0] || x[1] - y[1])
  let cur = 0, inFlight = 0
  for (const [, d] of evts) { cur += d; inFlight = Math.max(inFlight, cur) }
  return { period, results, inFlight }
}

/** Per-frame time windows for RT / NRT / post stages → shows N+1 RT overlapping N NRT. */
export function frameWindows(tl: Timeline, laneOfPid: (pid: string) => string | undefined): { frame: number; lane: string; start: number; end: number }[] {
  const acc = new Map<string, { frame: number; lane: string; start: number; end: number }>()
  for (const s of tl.slices) {
    if (s.frame === null || !s.nodeId) continue
    const lane = laneOfPid(pipelineIdOf(s.nodeId.replace(/^stage:/, '')))
    if (!lane) continue
    const k = `${s.frame}|${lane}`
    const a = acc.get(k) ?? { frame: s.frame, lane, start: Infinity, end: -Infinity }
    a.start = Math.min(a.start, s.start); a.end = Math.max(a.end, s.end)
    acc.set(k, a)
  }
  return [...acc.values()].sort((a, b) => a.frame - b.frame || a.start - b.start)
}
