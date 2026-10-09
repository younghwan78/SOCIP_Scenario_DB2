// Prediction ↔ measurement calibration (backend: /calibration/*, src/scenario_db/api/services/calibration.py)
import { getJson } from './api'
import type { CategoryFit } from './provenance'
import type { ClockView } from './clockResidency'

export type Category = 'cpu' | 'ip' | 'bw' | 'other'
export interface Total { mean: number | null; std: number | null; p95: number | null; ci_95: number[] | null; n: number | null }
export interface MeasRow {
  id: string; scenario_id: string; variant_id: string; project_ref: string | null; measured_at: string | null
  silicon_rev: string | null; sw_baseline_ref: string | null; thermal: string | null; total: Total; fps: number | null; rails: number; synthetic?: boolean
  /** category: worst CPU/IP/BW Δ and whether the total matches only by compensation (absent before the API update) */
  current_prediction: { id: string; total_mw: number; delta_pct: number | null; category?: CategoryFit | null } | null
  simulation: { id: string; total_mw: number | null; delta_pct: number | null; count: number; category?: CategoryFit | null } | null
}
export interface Rail { rail: string; category: Category; power_mw: number; std_mw: number; voltage_v: number | null; current_ma: number | null; domain: string | null }
export interface SplitRow { category: Category; prediction_mw: number | null; measurement_mw: number | null; delta_mw: number | null; delta_pct: number | null }
export type CondStatus = 'match' | 'mismatch' | 'unrecorded'
export interface Conditions { overall: 'equivalent' | 'reference' | 'unverified'; items: { item: string; measured: unknown; predicted: unknown; status: CondStatus }[] }
export const CONDITION_LABEL: Record<Conditions['overall'], string> = { equivalent: '조건 일치', reference: '참고 비교 (조건 불일치)', unverified: '조건 미기록' }
export interface PredictionCmp {
  conditions?: Conditions
  kind: 'current' | 'simulation'; id: string; label: string; total_mw: number | null; delta_pct: number | null
  split: Record<'cpu' | 'ip' | 'bw', number> | null; rows: SplitRow[] | null; run_id?: string; selection_rule?: string; statistic?: string
}
export interface MeasDetail {
  id: string; scenario_id: string; variant_id: string; project_ref: string | null; measured_at: string | null
  context: Record<string, string | number | null>; total: Total; fps: number | null; synthetic?: boolean; derived_from?: string[]
  frame_latency: { mean?: number; p95?: number } | null
  measured: { categories: Record<Category, number>; category_std: Record<Category, number>; rail_total_mw: number; rails: Rail[] }
  rail_domain_map_ref: string | null; unexplained_mw: number | null; predictions: PredictionCmp[]
  origin?: 'synthetic' | 'physical_capture' | 'unknown'; rail_map_basis?: 'pinned' | 'latest' | 'none'
  sw_tasks: { task: string; mean_ms?: number; p95_ms?: number; max_ms?: number; min_ms?: number; count?: number; thread?: string; cluster?: string }[]
  /** CPU cluster · DSU · GPU frequency residency (absent before the API update / null without residency) */
  clock_residency?: ClockView | null
}

export interface CoverageSim { id: string; at: string | null; tool?: string | null; tool_version?: string | null; source?: string | null; sw_baseline_ref?: string | null; total_mw?: number | null; shown?: boolean }
export interface CoverageMeas { id: string; at: string | null; origin: string; synthetic: boolean; sw_baseline_ref?: string | null; silicon_rev?: string | null; thermal?: string | null; build_id?: string | null; total_mw?: number | null; shown?: boolean }
export interface CoveragePrediction { id: string; total_mw: number | null; created_at?: string | null; run?: string | null; case_key?: string | null; selection_rule?: string | null; selected_by?: string | null; dvfs_table_ref?: string | null; supersedes?: string | null; version?: number }
export interface Coverage {
  simulation: number; measurement: number; synthetic: number; unknown?: number; current_prediction: CoveragePrediction | null
  /** API ≥ 2026-10-09: newest first, ``shown`` = the representative entry */
  simulations?: CoverageSim[]; measurements?: CoverageMeas[]
}

/** "PRED-3fa9c…" style short id: prefix + first 5 characters of the key. */
export function shortId(id: string | null | undefined, n = 5): string {
  if (!id) return '—'
  const m = /^([A-Za-z]+-)([0-9a-f]{12,})$/.exec(id)
  if (m) return `${m[1]}${m[2].slice(0, n)}…`
  return id.length > 32 ? `${id.slice(0, 28)}…` : id
}
/** Short ids that stay distinct inside one list: 5 characters, longer only where two ids collide (SCN-02). */
export function uniqueShortIds(ids: (string | null | undefined)[], n = 5): Map<string, string> {
  const out = new Map<string, string>()
  const list = [...new Set(ids.filter((x): x is string => !!x))]
  for (const id of list) {
    let k = n
    while (k < 32 && list.some((o) => o !== id && shortId(o, k) === shortId(id, k))) k += 1
    out.set(id, shortId(id, k))
  }
  return out
}
/** ISO timestamp → "2026-10-04" (local date of the recorded offset). */
export const dayOf = (at: string | null | undefined): string => (at ? at.slice(0, 10) : '날짜 없음')

export function simTooltip(c: Coverage): string {
  const sims = c.simulations ?? []
  if (!sims.length) return `simulation evidence ${c.simulation}건`
  return [`simulation evidence ${sims.length}건 (최신순, ▶ = 대표)`,
    ...sims.slice(0, 6).map((s) => `${s.shown ? '▶' : ' '} ${dayOf(s.at)} · ${s.tool ?? 'sim'} v${s.tool_version ?? '?'}${s.source ? ` (${s.source})` : ''} · SW ${s.sw_baseline_ref ?? '—'}${s.total_mw != null ? ` · ${s.total_mw.toFixed(0)} mW` : ''}\n    ${s.id}`),
    ...(sims.length > 6 ? [`… 외 ${sims.length - 6}건`] : [])].join('\n')
}
export function predictionTooltip(p: CoveragePrediction, short?: string): string {
  return [`등록 예측 ${short ?? shortId(p.id)} (클릭 = 전체 ID 복사: ${p.id})${p.version ? ` · v${p.version}` : ''} · ${dayOf(p.created_at)}`,
    p.total_mw != null ? `total ${p.total_mw.toFixed(0)} mW` : null,
    p.selection_rule ? `선정 ${p.selection_rule}${p.selected_by ? ` (${p.selected_by})` : ''}` : null,
    p.run ? `조합 탐색 run ${shortId(p.run)}` : null,
    p.dvfs_table_ref ? `DVFS ${p.dvfs_table_ref}` : null,
    p.supersedes ? `이전 등록 ${shortId(p.supersedes)} 대체` : null].filter(Boolean).join('\n')
}
export function measTooltip(c: Coverage): string {
  const ms = c.measurements ?? []
  if (!ms.length) return `실제 측정 ${c.measurement}건 · 합성 ${c.synthetic}건`
  return [`측정 evidence ${ms.length}건 (▶ = 대표: 최신 실측 → 합성 순)`,
    ...ms.slice(0, 6).map((m) => `${m.shown ? '▶' : ' '} ${dayOf(m.at)} · ${m.synthetic ? '합성' : '실측'} · ${m.silicon_rev ?? '—'} · SW ${m.sw_baseline_ref ?? '—'}${m.build_id ? ` · ${m.build_id}` : ''}${m.total_mw != null ? ` · ${m.total_mw.toFixed(0)} mW` : ' · power 없음'}\n    ${m.id}`),
    ...(ms.length > 6 ? [`… 외 ${ms.length - 6}건`] : [])].join('\n')
}
export const calibrationApi = {
  coverageSummary: () => getJson<Record<string, Record<'simulation' | 'measurement' | 'synthetic' | 'current_prediction', number>>>('/calibration/coverage-summary', {}, false),
  coverage: (scenarioId: string) => getJson<Record<string, Coverage>>('/calibration/coverage', { scenario_id: scenarioId }, false),
  measurements: (scenarioId?: string) => getJson<MeasRow[]>('/calibration/measurements', { scenario_id: scenarioId }, false),
  detail: (id: string) => getJson<MeasDetail>(`/calibration/measurements/${encodeURIComponent(id)}`, {}, false),
  ipBandwidth: (scenarioId: string, variantId: string, measurementId?: string) =>
    getJson<IpBandwidth>('/calibration/ip-bandwidth', { scenario_id: scenarioId, variant_id: variantId, measurement_id: measurementId }, false),
}

type Rw = { read: number | null; write: number | null; total: number | null }
export interface IpBwRow {
  node: string; hw_name?: string | null; ports: number; measured_ref: string | null
  pred: { read: number; write: number; total: number }; meas: (Rw & { read_p95?: number | null; write_p95?: number | null }) | null; delta_pct: Rw | null
}
export interface IpBandwidth {
  scenario_id: string; variant_id: string; rows: IpBwRow[]; note: string
  /** like-for-like check (PIPE-05): synthetic / unknown origin / SW / fps differences make it a reference comparison */
  comparability?: { equivalent: boolean; statistic: string; reasons: string[] } | null
  simulation: { id: string; at: string | null; tool_version?: string | null } | null
  measurement: { id: string; at: string | null; synthetic: boolean; sw_baseline_ref?: string | null; silicon_rev?: string | null } | null
  measurements: { id: string; at: string | null; synthetic: boolean }[]
  unmatched: { ref: string; read?: number | null; write?: number | null; total?: number | null }[]
}

export const CAT_LABEL: Record<Category, string> = { cpu: 'CPU (SW)', ip: 'IP (HW core)', bw: 'BW (MIF · DRAM)', other: '기타 (미모델)' }
export const CAT_COLOR: Record<Category, string> = { cpu: '#0072B2', ip: '#009E73', bw: '#E69F00', other: '#9A9387' }

/** |Δ%| badge class: ≤10% ok, ≤25% warn, else fail. */
export function errClass(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return ''
  const a = Math.abs(pct)
  return a <= 10 ? 'v-ok' : a <= 25 ? 'v-warn' : 'v-fail'
}
