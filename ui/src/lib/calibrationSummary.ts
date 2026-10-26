// Model-level prediction ↔ measurement view (backend: GET /calibration/summary).
// One representative capture per variant; category bias over all compared variants.
import { getJson } from './api'
import type { MeasDetail } from './calibration'

export type BiasCat = 'total' | 'cpu' | 'ip' | 'bw'
export type BiasVerdict = 'ok' | 'model_common' | 'bias' | 'scenario' | 'insufficient'
export interface BiasStats {
  n: number; median: number | null; p25: number | null; p75: number | null; min: number | null; max: number | null
  within10: number; within25: number; same_sign_pct: number | null; sign: number; verdict: BiasVerdict; label: string
}
export interface SummaryRow {
  scenario_id: string; variant_id: string; measurement_id: string; measured_at: string | null
  origin: string; synthetic: boolean; captures: number; fps: number | null
  meas: { total: number; cpu: number | null; ip: number | null; bw: number | null; other: number | null }
  pred: { id: string; total: number; cpu: number | null; ip: number | null; bw: number | null } | null
  delta_pct: Record<BiasCat, number | null> | null
  fit: { worst_category: string | null; worst_delta_pct: number | null; offsetting: boolean } | null
  conditions: string | null
  latency?: { pred_ms: number | null; meas_p95_ms: number | null; meas_mean_ms: number | null; delta_pct: number | null } | null
  rail_groups?: { key: string; label: string; category: string; meas_mw: number; pred_mw: number | null; delta_mw: number | null; delta_pct: number | null }[]
}
export interface RailBias extends Omit<BiasStats, 'label'> { key: string; label: string; category: string; label_verdict: string; median_meas_mw: number | null; median_abs_delta_mw: number | null }
export interface CorrectionPreview { label: string; factors: Record<'cpu' | 'ip' | 'bw', number>; median: number | null; within10: number; n: number; max_abs: number | null }
export interface CalSummary {
  scope: { scenario_id: string | null; project_ref: string | null; include_synthetic: boolean }
  coverage: { variants: number; with_prediction: number; with_measurement: number; compared: number; origin: Record<string, number>; captures: number }
  bias: Record<BiasCat, BiasStats>
  offsetting: number
  flat_cpu: { mw_at_base_fps: number; base_fps: number; count: number; n: number } | null
  unmodeled_share_pct: number | null
  rail_bias?: RailBias[]
  latency_bias?: BiasStats
  correction: { ratios: Partial<Record<'cpu' | 'ip' | 'bw', number>>; previews: CorrectionPreview[] }
  confidence: { grade: 'A' | 'B' | 'C'; reasons: string[]; meaning: string; real: number; compared: number }
  rows: SummaryRow[]
}

export const summaryApi = {
  get: (p: { scenarioId?: string; projectRef?: string; includeSynthetic?: boolean; physicalOnly?: boolean }) =>
    getJson<CalSummary>('/calibration/summary', { scenario_id: p.scenarioId, project_ref: p.projectRef,
      include_synthetic: p.includeSynthetic === false ? 'false' : undefined, physical_only: p.physicalOnly ? 'true' : undefined }, false),
}

export const BIAS_CATS: { k: BiasCat; label: string; color: string }[] = [
  { k: 'total', label: 'Total', color: '#4A5160' },
  { k: 'cpu', label: 'CPU', color: '#0072B2' },
  { k: 'ip', label: 'IP', color: '#009E73' },
  { k: 'bw', label: 'BW', color: '#E69F00' },
]

/** |Δ| band, same thresholds as errClass: ≤10 ok, ≤25 warn, else fail. */
export function band(v: number | null | undefined): '' | 'ok' | 'warn' | 'fail' {
  if (v === null || v === undefined) return ''
  const a = Math.abs(v)
  return a <= 10 ? 'ok' : a <= 25 ? 'warn' : 'fail'
}

export const GROUPS = ['FHD · QHD 30', 'UHD 30', '60 fps', '고속 (≥ 100 fps)', '8K', '멀티 카메라', '3rd-party · RCV · IQ', '기타'] as const
/** Display group of a variant (name + fps heuristic; generic pipeline names fall into 기타). */
export function groupOf(variantId: string, fps: number | null): string {
  const v = variantId.replace(/^cam-rec-/, '')
  if (/^(pip|rdual|rtriple|dual|triple)-/.test(v)) return '멀티 카메라'
  if (/^(3rdparty|rcv|iq-eval)/.test(v)) return '3rd-party · RCV · IQ'
  if (fps !== null && fps >= 100) return '고속 (≥ 100 fps)'
  if (/8k/.test(v)) return '8K'
  if (fps !== null && fps > 50) return '60 fps'
  if (/uhd/.test(v)) return 'UHD 30'
  if (/fhd|qhd/.test(v)) return 'FHD · QHD 30'
  return '기타'
}

/** Sum of |category gaps| (mW) incl. the unmodeled rails — the error a correct total can hide. */
export function absGapMw(r: SummaryRow): number | null {
  if (!r.pred) return null
  let s = r.meas.other ?? 0
  for (const c of ['cpu', 'ip', 'bw'] as const) {
    const p = r.pred[c], m = r.meas[c]
    if (p !== null && m !== null) s += Math.abs(m - p)
  }
  return s
}

export type MatrixSort = 'group' | 'total' | 'worst' | 'mw'
export function sortRows(rows: SummaryRow[], mode: MatrixSort): SummaryRow[] {
  const key: Record<Exclude<MatrixSort, 'group'>, (r: SummaryRow) => number> = {
    total: (r) => Math.abs(r.delta_pct?.total ?? -1),
    worst: (r) => Math.abs(r.fit?.worst_delta_pct ?? -1),
    mw: (r) => absGapMw(r) ?? -1,
  }
  if (mode === 'group') {
    const gi = (r: SummaryRow) => GROUPS.indexOf(groupOf(r.variant_id, r.fps) as typeof GROUPS[number])
    return [...rows].sort((a, b) => gi(a) - gi(b) || a.variant_id.localeCompare(b.variant_id))
  }
  return [...rows].sort((a, b) => key[mode](b) - key[mode](a))
}

export interface WaterfallStep { label: string; kind: 'total' | 'delta'; value: number; from: number; to: number; cat: 'total' | 'cpu' | 'ip' | 'bw' | 'other' }
/** Registered prediction → per-category (measured − predicted) → measured total. null when there is no
 *  registered prediction with a CPU / IP / BW split. Categories the prediction does not model count as
 *  their whole measured value (like the unmodeled rails). */
export function waterfall(d: Pick<MeasDetail, 'total' | 'measured' | 'predictions'>): { steps: WaterfallStep[]; gapAbs: number; offsetShare: number } | null {
  const cur = d.predictions.find((p) => p.kind === 'current')
  const total = d.total.mean
  if (!cur || !cur.rows || cur.total_mw === null || total === null || total === undefined) return null
  const predTotal = cur.total_mw
  const steps: WaterfallStep[] = [{ label: '등록 예측', kind: 'total', value: predTotal, from: 0, to: predTotal, cat: 'total' }]
  let run = predTotal
  let gapAbs = 0
  for (const c of ['cpu', 'ip', 'bw', 'other'] as const) {
    const meas = d.measured.categories[c] ?? 0
    const pred = c === 'other' ? 0 : (cur.rows.find((r) => r.category === c)?.prediction_mw ?? 0)
    const dv = meas - pred
    gapAbs += Math.abs(dv)
    steps.push({ label: c === 'other' ? '미모델' : c.toUpperCase(), kind: 'delta', value: dv, from: run, to: run + dv, cat: c })
    run += dv
  }
  // rails that the rail map did not attribute (rail sum ≠ total) close the bridge
  const rest = total - run
  if (Math.abs(rest) > 0.05) {
    gapAbs += Math.abs(rest)
    steps.push({ label: '미귀속', kind: 'delta', value: rest, from: run, to: total, cat: 'other' })
  }
  steps.push({ label: '실측', kind: 'total', value: total, from: 0, to: total, cat: 'total' })
  const diff = Math.abs(total - predTotal)
  return { steps, gapAbs, offsetShare: gapAbs > 0 ? Math.max(0, 1 - diff / gapAbs) : 0 }
}

export const signed = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(d)}`)
export const pctS = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${signed(v)}%`)
