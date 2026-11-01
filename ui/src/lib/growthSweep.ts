// CPU what-if: the MID rebalance over SW growth factors (POST /cpu/rebalance/sweep, CPU-02..05).
import { postCalculation } from './calculation'
import type { BwCoefficient, CpuRebalanceRequest } from './rebalance'

export interface SweepSplit { total_mw: number; feasible: boolean; mhz: Record<string, number>; mw: Record<string, number>; moved: string[]; min_slack_ms?: number | null }
export interface SweepStrategy { kind: 'concentrate' | 'spread'; clusters: string[]; total_mw: number; feasible: boolean; mhz: Record<string, number> }
export interface SweepPoint {
  growth: number; reference: SweepSplit | null; best: SweepSplit | null; strategies: SweepStrategy[]
  winner: string | null; big_gain_mw: number | null; cpu_bw_mbs: number | null; feasible_count: number | null
  /** CPU-09: cpu_bw_mbs × BW coefficient (API ≥ 2026-10-18) */
  bw_mw?: number | null
  /** slack_ms = SW room only; chain_slack_ms (API ≥ cpu-sweep/2) = the reference placement's RT-chain-aware slack */
  stages: { stage: string; sw_ms: number; room_ms: number; slack_ms: number; ok: boolean; chain_ms?: number | null; chain_slack_ms?: number }[]
}
export interface OppEvent { which: 'reference' | 'best'; growth_from: number; growth_to: number; cluster: string; mhz: [number, number]; delta_mw: number; significant?: boolean }
export interface GrowthSweep {
  profile_ref: string | null; power_params_ref: string; fps: number
  points: SweepPoint[]; events: OppEvent[]
  /** opp_step = the first significant OPP step-up (cpu-sweep/2; before: the largest) — every step-up in opp_steps */
  limits: { opp_step: OppEvent | null; opp_step_best_mw: number | null; timing_at: number | null; tolerance: number | null; binding: 'opp' | 'timing' | null
    opp_steps?: OppEvent[]; largest_step?: OppEvent | null; timing_fail_at?: number | null }
  basis?: { rev: string; timing_statistic: string; timing_coupling: string; rt_placement: string | null }
  elapsed_ms: number
  /** worker processes used (API ≥ 2026-10-18) */
  workers?: number
  bw_power?: BwCoefficient
}

type SweepStage = SweepPoint['stages'][number]

/** The stage slack the verdict uses: RT-chain-aware (cpu-sweep/2), else the SW room of older responses. */
export const verdictSlack = (st: SweepStage): number => st.chain_slack_ms ?? st.slack_ms

/** Tooltip row of one stage at a growth point: the verdict slack, with the SW room when the RT chain binds first. */
export function sweepStageTip(st: SweepStage): { k: string; v: string; tone: 'bad' | undefined } {
  const s = verdictSlack(st)
  const chainBinds = st.chain_slack_ms !== undefined && st.chain_slack_ms < st.slack_ms - 1e-6
  return {
    k: `${st.stage.toUpperCase()} 여유`,
    v: `${s.toFixed(2)} ms${chainBinds ? ` (RT chain · SW room ${st.slack_ms.toFixed(2)})` : ''}`,
    tone: s < 0 ? 'bad' : undefined,
  }
}

/** First growth at which ``cluster`` steps up on the reference placement (CPU-08). */
export function firstStepUp(s: GrowthSweep | null, cluster: string): OppEvent | null {
  return s?.events.find((e) => e.which === 'reference' && e.cluster === cluster && e.mhz[1] > e.mhz[0]) ?? null
}

/** Shared y maximum for small multiples (CPU-10). */
export function sweepYMax(sweeps: (GrowthSweep | null)[]): number {
  return Math.max(1, ...sweeps.flatMap((s) => (s?.points ?? []).flatMap((p) => [p.reference?.total_mw ?? 0, ...p.strategies.filter((x) => x.kind === 'concentrate' && x.feasible).map((x) => x.total_mw)])))
}

export const sweepApi = {
  run: (req: CpuRebalanceRequest & { growths: number[] }, signal?: AbortSignal) => postCalculation<GrowthSweep>('/cpu/rebalance/sweep', req, signal),
}

/** Growth grid: start..end with step (inclusive, ≤ 13 points, 2 decimals). */
export function growthGrid(start: number, end: number, step: number): number[] {
  if (!(step > 0) || !(end > start)) return [start, Math.max(start + 0.1, end)].map((g) => Math.round(g * 100) / 100)
  const boundedStep = Math.max(step, (end - start) / 12)
  const n = Math.floor((end - start) / boundedStep + 1e-9)
  const points = Array.from({ length: n + 1 }, (_, i) => Math.round((start + i * boundedStep) * 100) / 100)
  const last = Math.round(end * 100) / 100
  if (points[points.length - 1] !== last) {
    if (points.length === 13) points[12] = last
    else points.push(last)
  }
  return [...new Set(points)]
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
