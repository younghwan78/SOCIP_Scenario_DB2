// Prediction ↔ measurement calibration (backend: /calibration/*, src/scenario_db/api/services/calibration.py)
import { getJson } from './api'

export type Category = 'cpu' | 'ip' | 'bw' | 'other'
export interface Total { mean: number | null; std: number | null; p95: number | null; ci_95: number[] | null; n: number | null }
export interface MeasRow {
  id: string; scenario_id: string; variant_id: string; project_ref: string | null; measured_at: string | null
  silicon_rev: string | null; sw_baseline_ref: string | null; thermal: string | null; total: Total; fps: number | null; rails: number
  current_prediction: { id: string; total_mw: number; delta_pct: number | null } | null
  simulation: { id: string; total_mw: number | null; delta_pct: number | null; count: number } | null
}
export interface Rail { rail: string; category: Category; power_mw: number; std_mw: number; voltage_v: number | null; current_ma: number | null; domain: string | null }
export interface SplitRow { category: Category; prediction_mw: number | null; measurement_mw: number | null; delta_mw: number | null; delta_pct: number | null }
export interface PredictionCmp {
  kind: 'current' | 'simulation'; id: string; label: string; total_mw: number | null; delta_pct: number | null
  split: Record<'cpu' | 'ip' | 'bw', number> | null; rows: SplitRow[] | null; run_id?: string; selection_rule?: string; statistic?: string
}
export interface MeasDetail {
  id: string; scenario_id: string; variant_id: string; project_ref: string | null; measured_at: string | null
  context: Record<string, string | number | null>; total: Total; fps: number | null
  frame_latency: { mean?: number; p95?: number } | null
  measured: { categories: Record<Category, number>; category_std: Record<Category, number>; rail_total_mw: number; rails: Rail[] }
  rail_domain_map_ref: string | null; unexplained_mw: number | null; predictions: PredictionCmp[]
  sw_tasks: { task: string; mean_ms?: number; p95_ms?: number; max_ms?: number; min_ms?: number; count?: number; thread?: string; cluster?: string }[]
}

export const calibrationApi = {
  measurements: (scenarioId?: string) => getJson<MeasRow[]>('/calibration/measurements', { scenario_id: scenarioId }, false),
  detail: (id: string) => getJson<MeasDetail>(`/calibration/measurements/${encodeURIComponent(id)}`, {}, false),
}

export const CAT_LABEL: Record<Category, string> = { cpu: 'CPU (SW)', ip: 'IP (HW core)', bw: 'BW (MIF · DRAM)', other: '기타 (미모델)' }
export const CAT_COLOR: Record<Category, string> = { cpu: '#0072B2', ip: '#009E73', bw: '#E69F00', other: '#9A9387' }

/** |Δ%| badge class: ≤10% ok, ≤25% warn, else fail. */
export function errClass(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return ''
  const a = Math.abs(pct)
  return a <= 10 ? 'v-ok' : a <= 25 ? 'v-warn' : 'v-fail'
}
