// Prediction ↔ measurement calibration (backend: /calibration/*, src/scenario_db/api/services/calibration.py)
import { getJson, postJson } from './api'
import { currentReadSignal } from './readRequestScope'
import type { CategoryFit } from './provenance'
import type { ClockView } from './clockResidency'

export type Category = 'cpu' | 'ip' | 'bw' | 'other'
export interface Total { mean: number | null; std: number | null; p95: number | null; ci_95: number[] | null; n: number | null }
export interface MeasRow {
  id: string; scenario_id: string; variant_id: string; project_ref: string | null; measured_at: string | null
  silicon_rev: string | null; sw_baseline_ref: string | null; thermal: string | null; total: Total; fps: number | null; rails: number; synthetic?: boolean
  origin?: 'physical_capture' | 'synthetic' | 'unknown'
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
  /** CAL-09..11 drill-down against the registered prediction (absent before the API update) */
  drilldown?: Drilldown
}

export interface RailGroup {
  key: string; label: string; category: Category; meas_mw: number; pred_mw: number | null
  delta_mw: number | null; delta_pct: number | null; share_pct: number | null; note: string | null
  rails: { rail: string; mw: number }[]; pred_items: { name: string; mw: number; vdd?: string }[]
}
export interface SwCompareRow {
  task: string; assumed_ms: number | null; assumed_stat: string | null; mean_ms: number | null; p95_ms: number | null; max_ms: number | null
  delta_ms: number | null; delta_pct: number | null; assumed_margin_pct: number | null; measured_margin_pct: number | null
  status: 'within' | 'under_assumed' | 'over_budget' | 'measured_only' | 'assumed_only'
}
export interface Drilldown {
  rails: { groups: RailGroup[]; notes: string[]; cpu_clusters: { rail: string; cluster: string; mw: number; share_pct: number }[]; vdd_source: string | null }
  latency: { pred_ms: number | null; meas_p95_ms: number | null; meas_mean_ms: number | null; delta_pct: number | null } | null
  sw_stage: string | null; sw_budget_ms: number | null; statistic: string | null
  sw?: { statistic: string; budget_ms: number | null; rows: SwCompareRow[]; optimistic: number; compared: number; worst: SwCompareRow | null }
  clock?: { group: string; pred_mhz: number; dvfs_level: number | null; nodes: number; meas_mhz: number | null; meas_p50_mhz: number | null; delta_pct: number | null }[]
}

export interface CoverageSim { id: string; at: string | null; tool?: string | null; tool_version?: string | null; source?: string | null; sw_baseline_ref?: string | null; total_mw?: number | null; shown?: boolean; by?: string | null }
export interface CoverageMeas { id: string; at: string | null; origin: string; synthetic: boolean; sw_baseline_ref?: string | null; silicon_rev?: string | null; thermal?: string | null; build_id?: string | null; total_mw?: number | null; shown?: boolean }
export interface CoveragePrediction { id: string; total_mw: number | null; created_at?: string | null; run?: string | null; case_key?: string | null; selection_rule?: string | null; selected_by?: string | null; dvfs_table_ref?: string | null; supersedes?: string | null
  /** n-th registration of the variant (count, not a model version) — prefer ``revision`` */
  version?: number; revision?: number
  /** P0 model basis the number rests on (config profile · power params · DVFS · engine) */
  basis?: PredictionBasis
  /** SW timing source: measured trace's SW, else the project default */
  sw?: { ref: string | null; label: string; source: 'measured' | 'defined'; measurement_ref?: string | null; soc?: string | null; hash?: string | null }
  /** today's inputs vs the run's frozen inputs */
  freshness?: { status: 'fresh' | 'stale' | 'unknown'; reasons: string[]; changed: string[] }
}
export interface PredictionBasis {
  recorded: boolean; label: string; key: string
  config_profile_ref: string | null; config_version: number | null
  power_params_ref: string | null; power_params_version: number | null; power_params_hash?: string | null
  dvfs_table_ref: string | null; engine_rev: string | null
  /** registry basis (B<n>) the run resolved to; overrides non-empty = B<n>* */
  basis_id?: string | null; code?: string | null; basis_status?: string | null; overrides?: string[]
}

const DATA_SECTIONS = /^(variant_doc|pipeline|power_options)$/
/** Why a registered prediction is (not) current: ok · basis (config / params / DVFS / IP / engine) · data (variant YAML) · unknown. */
export function freshnessOf(p: CoveragePrediction): { level: 'ok' | 'basis' | 'data' | 'unknown'; text: string; detail: string[] } {
  const f = p.freshness
  if (!f || f.status === 'unknown') return { level: 'unknown', text: '?', detail: f?.reasons ?? ['판정 정보 없음'] }
  if (f.status === 'fresh') return { level: 'ok', text: '✓', detail: ['현재 입력으로 다시 계산해도 같은 결과'] }
  const data = f.changed.filter((c) => DATA_SECTIONS.test(c))
  const basis = f.changed.filter((c) => !DATA_SECTIONS.test(c))
  const engine = f.reasons.some((r) => r.startsWith('engine') || r.startsWith('판정 기준'))
  const unreadable = f.reasons.some((r) => r.includes('기록 없음') || r.includes('해석 실패'))
  const level = data.length && !basis.length && !engine ? 'data' : unreadable && !engine && !data.length ? 'unknown' : 'basis'
  return { level, text: level === 'data' ? '⚠ 데이터' : level === 'unknown' ? '?' : '⚠ 기준', detail: f.reasons }
}
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
    ...sims.slice(0, 6).map((s) => `${s.shown ? '▶' : ' '} ${dayOf(s.at)} · ${s.tool ?? 'sim'} v${s.tool_version ?? '?'}${s.source ? ` (${s.source})` : ''} · SW ${s.sw_baseline_ref ?? '—'}${s.total_mw != null ? ` · ${s.total_mw.toFixed(0)} mW` : ''}${s.by ? ` · by ${s.by}` : ''}\n    ${s.id}`),
    ...(sims.length > 6 ? [`… 외 ${sims.length - 6}건`] : [])].join('\n')
}
export function predictionTooltip(p: CoveragePrediction, short?: string, checking = false): string {
  const b = p.basis, f = freshnessOf(p)
  return [`등록 예측 ${short ?? shortId(p.id)} (클릭 = 전체 ID 복사: ${p.id}) · ${dayOf(p.created_at)}${(p.revision ?? p.version) ? ` · 등록 ${p.revision ?? p.version}회째` : ''}`,
    b ? `기준 ${b.label}` : null,
    b ? `  config ${b.config_profile_ref ? `${b.config_profile_ref}${b.config_version != null ? ` (v${b.config_version})` : ''}` : (b.recorded ? '기본' : '미기록 (이전 engine run)')}` : null,
    b ? `  power params ${b.power_params_ref ? `${b.power_params_ref}${b.power_params_version != null ? ` (v${b.power_params_version})` : ''}` : '기본 (내장 계수)'}` : null,
    b ? `  DVFS ${b.dvfs_table_ref ?? '미기록'} · engine ${b.engine_rev ?? '?'}` : null,
    p.sw ? (p.sw.source === 'measured' ? `SW timing ${p.sw.label} — 실측 trace ${p.sw.measurement_ref ?? ''} (${p.sw.ref})`
      : `SW timing ${p.sw.label} — scenario 정의값(assumed)${p.sw.hash ? `, 사용한 값의 hash #${p.sw.hash}` : ' (이전 run: 사용 값 미기록)'} · SW 버전과 무관`) : null,
    !p.freshness && checking ? '상태 확인 중' : `상태 ${f.text} — ${f.detail.join(' · ')}`,
    p.total_mw != null ? `total ${p.total_mw.toFixed(0)} mW` : null,
    p.selection_rule ? `선정 ${p.selection_rule}${p.selected_by ? ` (${p.selected_by})` : ''}` : null,
    p.run ? `조합 탐색 run ${shortId(p.run)}` : null,
    p.dvfs_table_ref ? `DVFS ${p.dvfs_table_ref}` : null,
    p.supersedes ? `이전 등록 ${shortId(p.supersedes)} 대체` : null].filter(Boolean).join('\n')
}
export const shownMeas = (c: Coverage | undefined) => (c?.measurements ?? []).find((x) => x.shown) ?? (c?.measurements ?? [])[0]
// only a prediction fed by a measured trace has a SW build to compare; defined timing has none
export const predSw = (c: Coverage) => (c.current_prediction?.sw?.source === 'measured' ? c.current_prediction.sw.ref : null)
export const swDiffers = (c: Coverage, m: CoverageMeas) => { const p = predSw(c); return !!(p && m.sw_baseline_ref && p !== m.sw_baseline_ref) }
/** what the 실측 cell shows (date · power · SW≠), so the idle-column check compares cells, not the date sort key */
export function measCellKey(c: Coverage | undefined): string | null {
  const m = shownMeas(c)
  if (!c || !m) return c && (c.measurement || c.synthetic) ? (c.measurement ? '실측' : '합성') : null
  return `${m.synthetic ? '합성 ' : ''}${(m.at ?? '').slice(5, 10).replace('-', '/') || '날짜?'}${m.total_mw != null ? ` · ${m.total_mw.toFixed(0)}` : ''}${swDiffers(c, m) ? ' · SW≠' : ''}`
}
export function measTooltip(c: Coverage): string {
  const ms = c.measurements ?? []
  if (!ms.length) return `실제 측정 ${c.measurement}건 · 합성 ${c.synthetic}건`
  return [`측정 evidence ${ms.length}건 (▶ = 대표: 최신 실측 → 합성 순)`,
    ...ms.slice(0, 6).map((m) => `${m.shown ? '▶' : ' '} ${dayOf(m.at)} · ${m.synthetic ? '합성' : '실측'} · ${m.silicon_rev ?? '—'} · SW ${m.sw_baseline_ref ?? '—'}${m.build_id ? ` · ${m.build_id}` : ''}${m.total_mw != null ? ` · ${m.total_mw.toFixed(0)} mW` : ' · power 없음'}\n    ${m.id}`),
    ...(ms.length > 6 ? [`… 외 ${ms.length - 6}건`] : [])].join('\n')
}
/** S5: power coefficient fit (per category k through the origin) and the params versions it publishes. */
export type FitCat = 'cpu' | 'ip' | 'bw'
export interface FitFactor { k: number | null; k_raw?: number; clamped?: boolean; n: number; rmse_before_mw?: number; rmse_after_mw?: number
  mape_before_pct?: number; mape_after_pct?: number; r2_after?: number | null; recommended?: boolean }
export interface FitRow { measurement_ref: string; scenario_id: string; variant_id: string; synthetic: boolean; measured_sw: boolean; verdict: string
  predicted: Record<FitCat | 'total', number>; measured: Partial<Record<FitCat | 'other' | 'total', number | null>>; after: Record<FitCat | 'total', number>
  delta_pct_before: number | null; delta_pct_after: number | null }
export interface PowerFit { base_params_ref: string; statistic: string; measured_sw: boolean; rows: FitRow[]; errors: { measurement_ref: string; variant_id: string; error: string }[]
  factors: Record<FitCat, FitFactor>; warnings: string[] }
export interface PowerParamsVersion { id: string; version: number; ref: string; soc_ref: string; status: string; description: string | null; calibrated: boolean; ip_power_scale: Record<string, number> }
export interface PowerParamsCreated { params_ref: string; id: string; version: number; applied: Partial<Record<FitCat, number>>; yaml: string; params_hash: string }

type CoverageCount = Pick<Coverage, 'measurement'>
/** Small batched projection; preserve per-scenario failure handling on older/erroring servers.
 * Matrix/Predictions call it without `projectRef`: per-scenario coverage was never project-scoped. */
async function coverageBatch(scenarioIds: string[], projectRef?: string): Promise<(readonly [string, Record<string, CoverageCount>] | null)[]> {
  const signal = currentReadSignal()
  const out: (readonly [string, Record<string, CoverageCount>] | null)[] = []
  const ids = [...new Set(scenarioIds)]
  for (let i = 0; i < ids.length; i += 25) {
    const chunk = ids.slice(i, i + 25)
    const query = new URLSearchParams(chunk.map((id) => ['scenario_ids', id]))
    if (projectRef) query.set('project_ref', projectRef)
    try {
      const batch = await getJson<Record<string, Record<string, CoverageCount>>>(`/calibration/coverage-counts?${query}`, {}, false, signal)
      for (const id of chunk) out.push([id, batch[id] ?? {}])
    } catch (error) {
      if (signal?.aborted) throw error
      out.push(...await Promise.all(chunk.map((id) => getJson<Record<string, Coverage>>('/calibration/coverage', { scenario_id: id }, false, signal).then((rows) => [id, rows] as const).catch((cause) => { if (signal?.aborted) throw cause; return null }))))
    }
  }
  return out
}

export const calibrationApi = {
  coverageBatch,
  coverageSummary: () => getJson<Record<string, Record<'simulation' | 'measurement' | 'synthetic' | 'current_prediction', number>>>('/calibration/coverage-summary', {}, false),
  coverage: (scenarioId: string) => getJson<Record<string, Coverage>>('/calibration/coverage', { scenario_id: scenarioId }, false),
  measurements: (scenarioId?: string, projectRef?: string) => getJson<MeasRow[]>('/calibration/measurements', { scenario_id: scenarioId, project_ref: projectRef }, false),
  detail: (id: string) => getJson<MeasDetail>(`/calibration/measurements/${encodeURIComponent(id)}`, {}, false),
  powerFit: (body: { project_ref: string; scenario_id?: string; base_params_ref?: string; config_profile_ref?: string | null; include_synthetic: boolean; statistic: string; measured_sw: boolean }) =>
    postJson<PowerFit>('/calibration/power-fit', body),
  createPowerParams: (fit: PowerFit, factors: Partial<Record<FitCat, number | null>>, description?: string) =>
    postJson<PowerParamsCreated>('/calibration/power-params', { base_params_ref: fit.base_params_ref, factors, statistic: fit.statistic, measured_sw: fit.measured_sw,
      source_evidence: fit.rows.map((r) => r.measurement_ref), synthetic_rows: fit.rows.filter((r) => r.synthetic).length, fit_stats: fit.factors, description }),
  powerParams: (socRef?: string) => getJson<PowerParamsVersion[]>('/calibration/power-params', { soc_ref: socRef }, false),
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
