// Architecture exploration → predictions (current/superseded) → review reports.
// Backend: /arch/exploration/runs, /arch/predictions/*, /arch/reports (src/scenario_db/api/routers/arch_exploration.py)
import { API_BASE, ApiError } from './api'
import { fetchAdmitted, type Statistic } from './timingBudget'
import type { VariantFailure } from '../components/VariantFailures'

export interface Quant { min: number; p25: number; median: number; p75: number; max: number }
/** Distribution keys always present (engine rev 1+); the BW IP/CPU keys exist from rev 2. */
export type Dist = Record<'total_mw' | 'cpu_mw' | 'hw_mw' | 'bw_mw' | 'bw_mbs', Quant> & Partial<Record<DistKey, Quant>>
export type DistKey = 'total_mw' | 'cpu_mw' | 'hw_mw' | 'bw_mw' | 'bw_ip_mw' | 'bw_cpu_mw' | 'bw_mbs' | 'bw_ip_mbs' | 'bw_cpu_mbs'
export interface Verified {
  ok: boolean; delta_pct: number; sim_total_mw: number; analytic_total_mw: number; sim_verdict: string
  /** engine rev ≥ 7: model consistency and re-applied constraints are reported separately */
  tolerance_pct?: number; sim_bw_mbs?: number; analytic_bw_mbs?: number; bw_delta_pct?: number
  power_match?: boolean; bw_match?: boolean; timing_pass?: boolean; constraints_pass?: boolean; reasons?: string[]
}
export type PowerCoverage = 'complete' | 'partial' | 'none'
export interface VariantStatus {
  timing_feasible: boolean; power_coverage: PowerCoverage; power_budget_status: 'n/a' | 'pass' | 'fail' | 'unknown'
  model_consistency_verified: boolean | null; constraints_verified: boolean | null
}
export interface ExpCase {
  key: string; statistic: Statistic; runtime_scale: number; compression: string[]; dvfs: Record<string, number>; dvfs_raise: number
  total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; bw_mbs: number; lossy: boolean; assumed_ratio: boolean
  // engine rev 2+: BW split into IP BW (HW nodes) and CPU BW (SW tasks)
  bw_ip_mw?: number; bw_cpu_mw?: number; bw_ip_mbs?: number; bw_cpu_mbs?: number
  verdict: string; eligible: boolean; verified?: Verified
}
export interface BufferRow {
  buffer: string; format: string; family: string; nodes: string[]; support: string; selectable: boolean; explored?: boolean
  skip_reason?: string | null; mode?: string; comp_ratio?: number; ratio_source?: string; lossy?: boolean
  raw_mbs?: number; delta_mbs?: number; delta_mw?: number; ports?: string[]; listed_modes?: Record<string, string[]>; unsupported_ports?: string[]
}
export interface DomainOpt { level: number; speed_mhz: number; voltage_mv: number; delta_mw: number; raise: boolean }
export interface DomainRow { domain: string; base_level: number; nodes: string[]; max_required_mhz: number; options: DomainOpt[] }
export interface MarginStage {
  stage: string; slack_ms: number; margin_pct: number; sw_ms: number; hw_ms: number; sw_share_pct: number
  latency_share_pct: number; bottleneck: string | null; bottleneck_ms: number; bottleneck_share_pct: number
}
export interface SwMargin {
  stages: MarginStage[]; worst: MarginStage | null; growth_tolerance: number | null; growth_tested_max: number | null; stat_spread_ms: number; verdict: string; recommendations: string[]
  /** engine rev ≥ 7: growth absorbed with the recommended DVFS levels held (robustness), vs re-selected (growth_tolerance) */
  growth_tolerance_fixed?: number | null; growth_fixed_rows?: { runtime_scale: number; ok: boolean; short_domains: string[] }[]
}
export interface SliceRow {
  statistic: Statistic; runtime_scale: number; verdict: { status: string; reasons: string[] }; intervals_ok: boolean
  power: { total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number }; bw: { total_mbs: number }
}
export interface VariantResult {
  scenario_id: string; variant_id: string; fps: number; period_ms: number; eis_on: boolean; mfc_dual: boolean
  spec_ok: boolean; spec_reasons: string[]; counts: { cases: number; eligible: number; sw_slices: number; compression_sets: number; dvfs_sets: number }
  distribution: Dist; baseline: ExpCase; recommended: ExpCase | null; alternatives: ExpCase[]
  /** engine rev ≥ 7: non-dominated eligible cases on power · BW · IQ risk · DVFS headroom */
  pareto?: (ExpCase & { iq_risk: number })[]
  slices: SliceRow[]; buffers: BufferRow[]; domains: DomainRow[]
  axis_spread: Record<'sw_statistic' | 'sw_growth' | 'compression' | 'dvfs_headroom', { min: number; max: number; range: number }>
  sw_margin: SwMargin; coverage?: { zero_power_ips: string[]; hw_power_modeled: boolean; cpu_power_modeled: boolean; power_coverage?: PowerCoverage }
  status?: VariantStatus
  warnings: string[]; dvfs_table_ref?: string | null; input_hash: string
  /** engine rev 4+: power-saving options explored on top of the variant (never variants themselves) */
  power_options?: PowerOptions
  /** engine rev 6+: every HW node's sim mode, coefficients and declared alternatives */
  ip_modes?: IpModeRow[]
}
export interface IpModeAlt { mode: string; unit_power_mw_mp: number | null; ppc: number | null; explorable: boolean; label?: string | null; note?: string | null }
export interface IpModeRow {
  node: string; ip_ref: string; hw_name: string; mode: string; declared: boolean
  unit_power_mw_mp: number | null; ppc: number | null; dvfs_group: string | null; power_mw: number | null; set_clock_mhz: number | null
  alternatives: IpModeAlt[]
}

// ---------------------------------------------------------------- power options (IQ 평가 대상)
export type ReviewStatus = 'candidate' | 'iq_eval' | 'adopted' | 'rejected'
export interface OptionItem {
  key: string; kind: 'knob' | 'ip_mode'; label: string; value: string; from: string; iq_eval: string; note?: string | null
  dimension?: string; node?: string; ip_ref?: string
  unit_power_mw_mp?: number | null; from_unit_power_mw_mp?: number | null; ppc?: number | null; from_ppc?: number | null; source?: string | null
}
export interface OptionDimension { id: string; kind: 'knob' | 'ip_mode'; label: string; current: string; node?: string; ip_ref?: string; items: OptionItem[] }
export interface OptionResult {
  key: string; items: string[]; labels: string[]; kinds: string[]; iq_eval: string; spec_ok: boolean; spec_reasons: string[]
  total_mw: number | null; delta_mw: number | null; delta_pct: number | null; delta_bw_mbs: number | null
  raw_delta_mw: number; raw_delta_pct: number | null
  attribution: { reference: string; delta_mw: number; by_category: Record<string, number>; factors: Factor[]; components?: Record<string, number> }
  fill_pct?: Record<string, number>; review_status?: ReviewStatus
}
export interface PowerOptions {
  status: 'ok' | 'none' | 'skipped'; dimensions: OptionDimension[]; notes: string[]; sets: number; max_sets: number
  results: OptionResult[]; best: string | null; errors: { key: string; error: string }[]
}
export interface ItemReview { status: ReviewStatus; scope: 'variant' | 'scenario' | null; note: string | null; updated_by?: string | null; updated_at?: string | null }
export interface BoardOptions {
  status: 'ok' | 'none' | 'skipped' | 'not_explored'; notes: string[]; sets?: number
  reference?: { rule: string; case_key: string; note: string | null } | null
  items: (OptionItem & { review: ItemReview })[]; results: OptionResult[]
  best: { key: string; labels: string[]; delta_mw: number; delta_pct: number | null; review_status: ReviewStatus } | null
}
export interface OptionReview {
  id: string; project_ref: string | null; scenario_id: string; variant_id: string; option_key: string; status: ReviewStatus
  note: string | null; history: { status: ReviewStatus; note: string | null; by: string | null; at: string }[]
  updated_by: string | null; updated_at: string | null
}
export const REVIEW: Record<ReviewStatus, { label: string; cls: string }> = {
  candidate: { label: '후보', cls: '' }, iq_eval: { label: 'IQ 평가 중', cls: 'v-warn' },
  adopted: { label: '채택', cls: 'v-ok' }, rejected: { label: '기각', cls: 'v-fail' },
}
export const REVIEW_ORDER: ReviewStatus[] = ['candidate', 'iq_eval', 'adopted', 'rejected']

/** Best spec-OK saving of a run variant (delta vs its recommended case). */
export function bestOption(po: PowerOptions | undefined): OptionResult | null {
  if (!po || po.status !== 'ok') return null
  return po.results.find((r) => r.key === po.best) ?? null
}
export interface RunMeta {
  id: string; title: string; scenario_type: string; project_ref: string | null; soc_ref: string | null; dvfs_table_ref: string | null
  engine_rev: string; created_by: string | null; created_at: string | null; config_profile_ref?: string | null
  summary: { variants: number; errors: number; spec_ok: number; cases: number; eligible_cases: number; verified: number; recommended_power_mw: [number, number] | null
    power_options?: { variants: number; sets: number; best_saving_mw: [number, number] | null } }
}
export interface RunDetail extends RunMeta { spec: Record<string, unknown>; variants: VariantResult[]; errors: VariantFailure[] }
export interface Power { total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; bw_ip_mw?: number; bw_cpu_mw?: number }
export interface BoardRow {
  id: string; scenario_id: string; variant_id: string; status: string; run_id: string; run_title: string | null; run_created_at: string | null
  case_key: string; selection_rule: string; selected_by: string; reason: string | null; created_at: string | null
  fps: number; power: Power; bw_mbs: number; distribution: Dist | null; compression: string[]; dvfs: Record<string, number>
  verdict: string; eligible_cases: number; alternatives: number; verified: Verified | null; statistic: Statistic; runtime_scale: number
  previous: { id: string; total_mw: number; delta_mw: number } | null
  power_options?: BoardOptions
}
export interface HistoryRow { id: string; status: string; run_id: string; selection_rule: string; reason: string | null; created_at: string | null; total_mw: number; power: Power; bw_mbs: number }
export interface Factor { category: string; item: string; delta_mw: number; detail: string }
export interface Attribution {
  old_total_mw: number; new_total_mw: number; delta_mw: number; delta_pct: number | null
  components: { cpu_mw: number; hw_mw: number; bw_mw: number; bw_ip_mw?: number; bw_cpu_mw?: number }; by_category: Record<string, number>; factors: Factor[]
  residual_mw: number; context_changes: { item: string; old: unknown; new: unknown }[]
}
export interface ReportMeta {
  id: string; title: string; status: 'draft' | 'published'; target_soc_ref: string | null; project_ref: string | null; scenario_type: string
  run_ids: string[]; dvfs_table_ref: string | null; engine_rev: string; html_sha256: string; generated_by: string | null; generated_at: string | null
  spec_ok: number | null; explored: number | null
  /** latest review entry (publish needs reviewer + note); absent before API 0023 */
  review?: { status: string; reviewer: string | null; note: string | null; by: string | null; at: string } | null; review_count?: number
}

export interface RunOptions {
  statistics: Statistic[]; runtime_scales: number[]; dvfs_headroom_levels: number
  modes: ('lossy' | 'lossless')[]; max_buffers: number; allow_lossy: boolean; objective_statistic: Statistic; objective_scale: number
  /** compression only on DMA whose endpoints declare support (IP catalog) */
  require_declared: boolean
  /** power-saving options: knob values (knobs.yaml explore) / substitute IP modes (sim.modes substitutes) */
  options: { knobs: boolean; modes: boolean; max_sets: number }
}
export const DEFAULT_RUN: RunOptions = {
  statistics: ['mean', 'max'], runtime_scales: [1.0, 1.1, 1.2], dvfs_headroom_levels: 1,
  modes: ['lossy'], max_buffers: 8, allow_lossy: true, objective_statistic: 'max', objective_scale: 1.0, require_declared: true,
  options: { knobs: true, modes: true, max_sets: 64 },
}

/** Request body for POST /arch/exploration/runs. */
export function runBody(scenarioIds: string[], title: string, scenarioType: string, o: RunOptions, configProfileRef?: string | null) {
  const scales = [...new Set([...o.runtime_scales, o.objective_scale])].sort((a, b) => a - b)
  const stats = [...new Set([...o.statistics, o.objective_statistic])]
  return {
    title: title || undefined, scenario_type: scenarioType || undefined, scenario_ids: scenarioIds,
    config_profile_ref: configProfileRef ?? undefined,
    spec: {
      axes: { statistics: stats, runtime_scales: scales, dvfs_headroom_levels: o.dvfs_headroom_levels,
        compression: { enabled: o.modes.length > 0 && o.max_buffers > 0, modes: o.modes.length ? o.modes : ['lossy'], max_buffers: o.max_buffers, require_declared: o.require_declared },
        power_options: { enabled: o.options.knobs || o.options.modes, include_knobs: o.options.knobs, include_modes: o.options.modes, max_sets: o.options.max_sets } },
      constraints: { allow_lossy: o.allow_lossy },
      objective: { statistic: o.objective_statistic, runtime_scale: o.objective_scale },
    },
  }
}

/** Case count per variant before running (guards the 200k server limit). */
export function caseCount(o: RunOptions, domains = 3): number {
  const slices = new Set([...o.statistics, o.objective_statistic]).size * new Set([...o.runtime_scales, o.objective_scale]).size
  const comp = o.modes.length ? 2 ** o.max_buffers : 1
  return slices * comp * (o.dvfs_headroom_levels + 1) ** domains
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetchAdmitted(`${API_BASE}${path}`, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined })
  if (!res.ok) {
    let detail = ''
    try { const j = await res.json() as { detail?: unknown }; detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j) } catch { /* not json */ }
    throw new ApiError(`${res.status} ${res.statusText} — ${path}${detail ? ` · ${detail}` : ''}`, res.status)
  }
  return res.json() as Promise<T>
}
const q = (p: Record<string, string | undefined>) => { const s = new URLSearchParams(Object.entries(p).filter(([, v]) => v) as [string, string][]).toString(); return s ? `?${s}` : '' }

export const archApi = {
  /** projectRef omitted = every project (explicit comparison mode) */
  runs: (projectRef?: string) => send<RunMeta[]>('GET', `/arch/exploration/runs${q({ project_ref: projectRef })}`),
  run: (id: string) => send<RunDetail>('GET', `/arch/exploration/runs/${encodeURIComponent(id)}`),
  createRun: (body: ReturnType<typeof runBody>) => send<RunDetail>('POST', '/arch/exploration/runs', body),
  promote: (runId: string, variantIds?: string[], caseKey?: string, reason?: string, scenarioId?: string, expectedProject?: string) =>
    send<{ promoted: { id: string; variant_id: string; total_mw: number }[]; skipped: { variant_id: string; reason: string }[] }>(
      'POST', '/arch/predictions/promote', { run_id: runId, variant_ids: variantIds, case_key: caseKey, reason, scenario_id: scenarioId, expected_project_ref: expectedProject }),
  board: (scenarioId?: string) => send<{ rows: BoardRow[] }>('GET', `/arch/predictions/board${q({ scenario_id: scenarioId })}`),
  optionReviews: (scenarioId?: string) => send<OptionReview[]>('GET', `/arch/power-options/reviews${q({ scenario_id: scenarioId })}`),
  setOptionReview: (body: { scenario_id: string; variant_id?: string; option_key: string; status: ReviewStatus; note?: string }) =>
    send<OptionReview>('PUT', '/arch/power-options/reviews', body),
  history: (scenarioId: string, variantId: string) => send<HistoryRow[]>('GET', `/arch/predictions/history${q({ scenario_id: scenarioId, variant_id: variantId })}`),
  compare: (p: { old_id?: string; new_id?: string; scenario_id?: string; variant_id?: string }) =>
    send<{ old: HistoryRow; new: HistoryRow; attribution: Attribution }>('GET', `/arch/predictions/compare${q(p)}`),
  reports: () => send<ReportMeta[]>('GET', '/arch/reports'),
  createReport: (runId: string, title?: string) => send<ReportMeta>('POST', '/arch/reports', { run_id: runId, title }),
  setReportStatus: (id: string, status: 'draft' | 'published', review?: { reviewer: string; note: string }) =>
    send<ReportMeta>('PATCH', `/arch/reports/${encodeURIComponent(id)}`, { status, ...review }),
  reportXlsxUrl: (id: string) => `${API_BASE}/arch/reports/${encodeURIComponent(id)}/xlsx`,
  reportPackageUrl: (id: string) => `${API_BASE}/arch/reports/${encodeURIComponent(id)}/package`,
  reportStale: (id: string) => send<{ stale: boolean; changed: { variant_id: string }[] }>('GET', `/arch/reports/${encodeURIComponent(id)}/stale`),
  reportHtmlUrl: (id: string) => `${API_BASE}/arch/reports/${encodeURIComponent(id)}/html`,
}

// ---------------------------------------------------------------- helpers
// Power components: blue / green / orange (Okabe-Ito — separable incl. color-vision deficiency)
export const PCOL = { cpu: '#0072B2', bwcpu: '#56B4E9', hw: '#009E73', bw: '#E69F00', total: '#4A5160' } as const
export const METRIC_COLOR: Record<DistKey, string> = {
  total_mw: PCOL.total, cpu_mw: PCOL.cpu, hw_mw: PCOL.hw, bw_mw: PCOL.bw, bw_ip_mw: PCOL.bw, bw_cpu_mw: PCOL.bwcpu,
  bw_mbs: PCOL.bw, bw_ip_mbs: PCOL.bw, bw_cpu_mbs: PCOL.bwcpu,
}

/** Stack order CPU → CPU BW → IP core → IP BW (runs from engine rev 1 have only total BW → shown as IP BW). */
export function powerParts(p: Power): { key: 'cpu' | 'bwcpu' | 'hw' | 'bw'; label: string; mw: number }[] {
  const cpuBw = p.bw_cpu_mw ?? 0
  const ipBw = p.bw_ip_mw ?? p.bw_mw - cpuBw
  return [
    { key: 'cpu', label: 'CPU (SW)', mw: p.cpu_mw }, { key: 'bwcpu', label: 'CPU BW', mw: cpuBw },
    { key: 'hw', label: 'IP (HW core)', mw: p.hw_mw }, { key: 'bw', label: 'IP BW', mw: ipBw },
  ]
}
export const short = (v: string) => v.replace(/^cam-rec-/, '').replace(/^cam-prev-/, 'prev-')
export const levels = (d: Record<string, number> | undefined) => Object.entries(d ?? {}).sort().map(([k, v]) => `${k}:L${v}`).join(' ')

/** Case delta vs the recommended case, per component. */
export function caseDelta(c: ExpCase, ref: ExpCase) {
  return { total: c.total_mw - ref.total_mw, cpu: c.cpu_mw - ref.cpu_mw, hw: c.hw_mw - ref.hw_mw, bw: c.bw_mw - ref.bw_mw, bw_mbs: c.bw_mbs - ref.bw_mbs }
}

/** Waterfall steps for an attribution (top N factors + '기타'). */
export function waterfall(a: Attribution, n = 10): { label: string; start: number; end: number; delta: number; category: string }[] {
  const top = a.factors.slice(0, n)
  const rest = a.factors.slice(n).reduce((s, f) => s + f.delta_mw, 0) + a.residual_mw
  const steps: { label: string; start: number; end: number; delta: number; category: string }[] = []
  let cur = a.old_total_mw
  for (const f of top) { steps.push({ label: `${f.item}`, start: cur, end: cur + f.delta_mw, delta: f.delta_mw, category: f.category }); cur += f.delta_mw }
  if (Math.abs(rest) >= 0.05) { steps.push({ label: '기타', start: cur, end: cur + rest, delta: rest, category: '기타' }); cur += rest }
  return steps
}

export const CAT_COLOR: Record<string, string> = {
  'SW runtime': '#0072B2', 'SW task 추가': '#0072B2', 'SW task 제거': '#0072B2',
  'IP workload': '#009E73', 'IP 추가': '#009E73', 'IP 제거': '#009E73', 'IP DVFS 전압': '#56B4E9',
  'BW traffic': '#E69F00', Compression: '#D55E00', 기타: '#9A9387',
}

/** Variant ids are only unique within a scenario. */
export const variantKey = (v: { scenario_id: string; variant_id: string }): string => JSON.stringify([v.scenario_id, v.variant_id])

/** Power coverage of a variant (older runs: derived from the zero-power IP list). */
export function coverageOf(v: Pick<VariantResult, 'status' | 'coverage'>): PowerCoverage | undefined {
  const c = v.status?.power_coverage ?? v.coverage?.power_coverage
  if (c) return c
  if (!v.coverage) return undefined
  if (!v.coverage.hw_power_modeled) return 'none'
  return v.coverage.zero_power_ips.length ? 'partial' : 'complete'
}

/** Variants a bulk "register lowest power" would promote (server rule: spec OK only). */
export function promoteTargets(run: Pick<RunDetail, 'variants'>): VariantResult[] {
  return run.variants.filter((v) => v.spec_ok && v.recommended)
}
