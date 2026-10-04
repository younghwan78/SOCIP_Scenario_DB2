// Pipeline Timing "예측 ↔ 실측": align two traces (predicted vs measured) by pipeline node and output stream.
import type { ViewResponse } from './api'
import { analyse, stageTimings, type StageTiming } from './cadence'
import type { Timeline } from './timeline'

export interface IpDelta {
  pid: string; lane: string | undefined
  a?: StageTiming; b?: StageTiming
  dStart: number | null; dDur: number | null; dDurPct: number | null
  /** measured / predicted duration: a per-IP correction factor candidate */
  factor: number | null
}
export interface StreamDelta {
  id: string; label: string
  a?: { fps: number | null; interval: number | null; jitter: number | null; latency: number | null; latMax: number | null; drops: number }
  b?: StreamDelta['a']
}
export interface TimingComparison {
  ips: IpDelta[]; streams: StreamDelta[]; onlyA: string[]; onlyB: string[]
  byLane: { lane: string; a: number; b: number; d: number }[]
  period: number | null
}

const HW_LANES = new Set(['rt', 'nrt', 'm2m', 'codec', 'display'])

export function compareTimelines(a: Timeline, b: Timeline, view: ViewResponse | undefined, fps: number | null, laneOfPid: (pid: string) => string | undefined): TimingComparison {
  const ta = stageTimings(a), tb = stageTimings(b)
  const pids = [...new Set([...ta.keys(), ...tb.keys()])]
  const ips: IpDelta[] = pids.map((pid) => {
    const x = ta.get(pid), y = tb.get(pid)
    const dDur = x && y ? y.dur - x.dur : null
    return { pid, lane: laneOfPid(pid), a: x, b: y, dStart: x && y ? y.offset - x.offset : null, dDur,
      dDurPct: x && y && x.dur > 0 ? (100 * (y.dur - x.dur)) / x.dur : null, factor: x && y && x.dur > 0 ? y.dur / x.dur : null }
  }).sort((p, q) => (p.a?.offset ?? p.b?.offset ?? 0) - (q.a?.offset ?? q.b?.offset ?? 0))
  const sa = analyse(a, view, fps), sb = analyse(b, view, fps)
  const pick = (r: (typeof sa.results)[number]) => ({ fps: r.fpsAchieved, interval: r.box?.mean ?? null, jitter: r.box?.std ?? null,
    latency: r.latBox?.mean ?? null, latMax: r.latBox?.max ?? null, drops: r.drops })
  const ids = [...new Set([...sa.results, ...sb.results].filter((r) => r.stream.kind !== 'input').map((r) => r.stream.id))]
  const streams: StreamDelta[] = ids.map((id) => {
    const x = sa.results.find((r) => r.stream.id === id), y = sb.results.find((r) => r.stream.id === id)
    return { id, label: (x ?? y)!.stream.label, a: x ? pick(x) : undefined, b: y ? pick(y) : undefined }
  })
  const lanes = new Map<string, { a: number; b: number }>()
  for (const d of ips) {
    if (!d.a || !d.b) continue
    const k = d.lane && HW_LANES.has(d.lane) ? 'HW' : d.lane === 'sw' ? 'SW' : d.lane ?? 'other'
    const cur = lanes.get(k) ?? { a: 0, b: 0 }
    cur.a += d.a.dur; cur.b += d.b.dur
    lanes.set(k, cur)
  }
  return {
    ips, streams, onlyA: ips.filter((d) => d.a && !d.b).map((d) => d.pid), onlyB: ips.filter((d) => d.b && !d.a).map((d) => d.pid),
    byLane: [...lanes.entries()].map(([lane, v]) => ({ lane, a: v.a, b: v.b, d: v.b - v.a })), period: sa.period,
  }
}

/** severity of a relative duration error */
export const errTone = (pct: number | null) => (pct === null ? '' : Math.abs(pct) <= 10 ? 'v-ok' : Math.abs(pct) <= 25 ? 'v-warn' : 'v-fail')

/** JSON of per-IP measured/predicted factors (candidate runtime scale per IP for the simulation profile). */
export function factorJson(c: TimingComparison, meta: { predicted: string; measured: string }): string {
  return JSON.stringify({ predicted: meta.predicted, measured: meta.measured,
    factors: Object.fromEntries(c.ips.filter((d) => d.factor !== null).map((d) => [d.pid, Math.round(d.factor! * 1000) / 1000])) }, null, 1)
}
