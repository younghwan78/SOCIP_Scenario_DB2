// CPU what-if: the MID rebalance over SW growth factors (POST /cpu/rebalance/sweep, CPU-02..05).
import { postAdmitted } from './timingBudget'
import type { CpuRebalanceRequest } from './rebalance'

export interface SweepSplit { total_mw: number; feasible: boolean; mhz: Record<string, number>; mw: Record<string, number>; moved: string[]; min_slack_ms?: number | null }
export interface SweepStrategy { kind: 'concentrate' | 'spread'; clusters: string[]; total_mw: number; feasible: boolean; mhz: Record<string, number> }
export interface SweepPoint {
  growth: number; reference: SweepSplit | null; best: SweepSplit | null; strategies: SweepStrategy[]
  winner: string | null; big_gain_mw: number | null; cpu_bw_mbs: number | null; feasible_count: number | null
  stages: { stage: string; sw_ms: number; room_ms: number; slack_ms: number; ok: boolean }[]
}
export interface OppEvent { which: 'reference' | 'best'; growth_from: number; growth_to: number; cluster: string; mhz: [number, number]; delta_mw: number }
export interface GrowthSweep {
  profile_ref: string | null; power_params_ref: string; fps: number
  points: SweepPoint[]; events: OppEvent[]
  limits: { opp_step: OppEvent | null; opp_step_best_mw: number | null; timing_at: number | null; tolerance: number | null; binding: 'opp' | 'timing' | null }
  elapsed_ms: number
}

export const sweepApi = {
  run: (req: CpuRebalanceRequest & { growths: number[] }) => postAdmitted<GrowthSweep>('/cpu/rebalance/sweep', req),
}

/** Growth grid: start..end with step (inclusive, ≤ 13 points, 2 decimals). */
export function growthGrid(start: number, end: number, step: number): number[] {
  if (!(step > 0) || !(end > start)) return [start, Math.max(start + 0.1, end)].map((g) => Math.round(g * 100) / 100)
  const n = Math.min(12, Math.round((end - start) / step))
  return Array.from({ length: n + 1 }, (_, i) => Math.round((start + i * step) * 100) / 100)
}

export const strategyKey = (s: SweepStrategy) => `${s.kind}:${s.clusters.join('+')}`
export const strategyLabel = (s: SweepStrategy) => `${s.clusters.map((c) => c.replace(/^MID_/, '')).join(' + ')}${s.kind === 'concentrate' ? ' 집중' : ''}`

/** Heatmap rows: growth × strategy (union of columns, concentrate first, then by cluster count). */
export function strategyMatrix(points: SweepPoint[]): { cols: { key: string; label: string; kind: string; n: number }[]; rows: { growth: number; cells: (SweepStrategy | null)[]; best: number | null }[] } {
  const cols = new Map<string, { key: string; label: string; kind: string; n: number }>()
  for (const p of points) for (const s of p.strategies) cols.set(strategyKey(s), { key: strategyKey(s), label: strategyLabel(s), kind: s.kind, n: s.clusters.length })
  const order = [...cols.values()].sort((a, b) => (a.kind === b.kind ? a.n - b.n || a.label.localeCompare(b.label) : a.kind === 'concentrate' ? -1 : 1))
  const rows = points.map((p) => {
    const cells = order.map((c) => p.strategies.find((s) => strategyKey(s) === c.key) ?? null)
    const feas = cells.map((c, i) => ({ c, i })).filter((x) => x.c && x.c.feasible)
    const best = feas.length ? feas.reduce((a, b) => (b.c!.total_mw < a.c!.total_mw ? b : a)).i : null
    return { growth: p.growth, cells, best }
  })
  return { cols: order, rows }
}

/** Best feasible spread / concentrate totals of one point. */
export function spreadVsConcentrate(p: SweepPoint): { spread: SweepStrategy | null; concentrate: SweepStrategy | null } {
  const pick = (k: string) => p.strategies.filter((s) => s.kind === k && s.feasible).sort((a, b) => a.total_mw - b.total_mw)[0] ?? null
  return { spread: pick('spread'), concentrate: pick('concentrate') }
}

/** Clusters ordered as the topology (dsu last). */
export const mhzClusters = (p: SweepPoint | undefined) => Object.keys(p?.reference?.mhz ?? {}).filter((c) => c !== 'dsu')
