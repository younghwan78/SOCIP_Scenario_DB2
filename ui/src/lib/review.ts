// Project review policy (project.globals.review_policy): throughput judgement, power reference (전과제 대비),
// thermal-watch list with pre-computed power reduction menus.
import { getJson } from './api'
import { useAsync } from './route'
import type { ThroughputModel } from './timingBudget'

export interface ReviewPolicy {
  declared: boolean; throughput_model: ThroughputModel; max_latency_frames: number | null
  register_baseline?: 'min_power' | 'iq_keep' | null
  power_reference: { project_ref: string | null; values_mw: Record<string, number>; tolerance_pct: number; source_note: string | null } | null
  thermal_watch: { scenario_ref: string; variant_ref: string; label: string | null; reduction_pct: number[]; note: string | null }[]
}
export interface PowerRef { mw: number; source: 'explicit' | 'prediction' | 'measurement' | 'synthetic'; project_ref: string | null; id: string | null; at: string | null; note?: string | null }
export interface References { policy: ReviewPolicy; tolerance_pct: number | null; references: Record<string, PowerRef> }
export interface PowerJudge { reference_mw: number; delta_mw: number; delta_pct: number | null; status: 'ok' | 'similar' | 'over'; source: PowerRef['source'] }
export interface MenuItem {
  key: string; label: string; kind: 'dvfs' | 'lossy' | 'option'; feasible: boolean; cost: string; delta_mw: number
  range_mw?: [number, number]; always_beneficial?: boolean; latency_ms?: number | null; exclusive: string
  /** EXP-06: stored IQ review of an option (candidate · iq_eval · adopted · rejected) */
  iq_status?: 'candidate' | 'iq_eval' | 'adopted' | 'rejected'; review?: { status: string; scope: string | null; note: string | null; updated_by?: string | null; updated_at?: string | null } | null
}
export interface ReductionPlan {
  ask_pct: number; need_mw: number; picked: string[]; saving_mw: number; achieved: boolean; iq_cost: boolean
  /** IQ items in the plan that are not adopted yet */
  iq_pending?: string[]; scope?: 'approved'
}
/** EXP-04: a sibling variant that drops performance (fps / resolution …) and its registered power. */
export interface PerfTrade {
  variant_id: string; total_mw: number; delta_mw: number; delta_pct: number | null
  changes: { key: string; from: unknown; to: unknown }[]; verdict: string | null; prediction_id: string; also?: string[]
}
export interface WatchItem {
  scenario_id: string; variant_id: string; label: string; note: string | null; prediction_id: string | null; run_id: string | null
  current_mw: number | null; baseline: 'iq_keep' | 'registered'; registered_mw: number | null; registered_lossy: boolean
  throughput_model: ThroughputModel; verdict: string | null; reference: PowerJudge | null
  menu: MenuItem[]; plans: ReductionPlan[]; notes: string[]
  approved_plans?: ReductionPlan[]; trades?: PerfTrade[]
}
export const IQ_LABEL: Record<string, string> = { candidate: '미평가', iq_eval: 'IQ 평가 중', adopted: 'IQ 승인', rejected: 'IQ 반려' }
export const IQ_CLASS: Record<string, string> = { candidate: 'v-info', iq_eval: 'v-warn', adopted: 'v-ok', rejected: 'v-fail' }
const TRADE_KEY: Record<string, string> = { fps: 'fps', resolution: '해상도', stabilization: '손떨림 보정', hdr: 'HDR', power_saving_mode: '절전 모드', sensor_mode: 'sensor mode' }
export const tradeText = (c: PerfTrade['changes'][number]) => `${TRADE_KEY[c.key] ?? c.key} ${String(c.from)}→${String(c.to)}`
export interface ThermalWatch { project_ref: string; policy: ReviewPolicy; items: WatchItem[] }

export const reviewApi = {
  references: (projectRef: string) => getJson<References>('/review/references', { project_ref: projectRef }, false),
  thermalWatch: (projectRef: string, cfg?: string | null) => getJson<ThermalWatch>('/review/thermal-watch', { project_ref: projectRef, config_profile_ref: cfg ?? undefined }, false),
}

export const JUDGE_LABEL: Record<PowerJudge['status'], string> = { ok: '전과제 이하', similar: '유사', over: '초과' }
export const JUDGE_CLASS: Record<PowerJudge['status'], string> = { ok: 'v-ok', similar: 'v-warn', over: 'v-fail' }

/** Same rule as the API (services/review.judge_power): <= ref ok, <= ref x (1 + tol) similar, else over. */
export function judgePower(current: number | null | undefined, ref: PowerRef | undefined, tolPct: number | null | undefined): PowerJudge | null {
  if (current === null || current === undefined || !ref) return null
  const delta = current - ref.mw
  const pct = ref.mw ? (100 * delta) / ref.mw : null
  const status: PowerJudge['status'] = delta <= 0 ? 'ok' : pct !== null && pct <= (tolPct ?? 0) ? 'similar' : 'over'
  return { reference_mw: ref.mw, delta_mw: delta, delta_pct: pct, status, source: ref.source }
}

/** Project review references; null while loading or when the API has no review endpoints (older server). */
export function useReferences(project: string | undefined): References | null {
  const q = useAsync(() => (project ? reviewApi.references(project).catch(() => null) : Promise.resolve(null)), [project])
  return q.data ?? null
}
