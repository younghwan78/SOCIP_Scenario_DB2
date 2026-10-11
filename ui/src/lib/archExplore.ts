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
  ok: boolean; delta_pct: number | null; sim_total_mw: number; analytic_total_mw: number; sim_verdict: string
  /** engine rev ≥ 7: model consistency and re-applied constraints are reported separately */
  tolerance_pct?: number; sim_bw_mbs?: number; analytic_bw_mbs?: number; bw_delta_pct?: number | null
  power_match?: boolean; bw_match?: boolean; timing_pass?: boolean; constraints_pass?: boolean; reasons?: string[]
}
export type PowerCoverage = 'complete' | 'partial' | 'none'
export interface VariantStatus {
  timing_feasible: boolean; power_coverage: PowerCoverage; power_budget_status: 'n/a' | 'pass' | 'fail' | 'unknown'
  model_consistency_verified: boolean | null; constraints_verified: boolean | null
}
export interface ExpCase {
  key: string; statistic: Statistic; runtime_scale: number; compression: string[]; dvfs: Record<string, number>; dvfs_raise: number
  /** engine rev ≥ 11: buffer -> chosen mode (lossless and lossy are separate choices) */
  compression_modes?: Record<string, string>
  total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; bw_mbs: number; lossy: boolean; assumed_ratio: boolean
  // engine rev 2+: BW split into IP BW (HW nodes) and CPU BW (SW tasks)
  bw_ip_mw?: number; bw_cpu_mw?: number; bw_ip_mbs?: number; bw_cpu_mbs?: number
  verdict: string; eligible: boolean; verified?: Verified
}
export interface BufferRow {
  buffer: string; format: string; family: string; nodes: string[]; support: string; selectable: boolean; explored?: boolean
  skip_reason?: string | null; mode?: string; comp_ratio?: number; ratio_source?: string; lossy?: boolean
  raw_mbs?: number; delta_mbs?: number; delta_mw?: number; ports?: string[]; listed_modes?: Record<string, string[]>; unsupported_ports?: string[]
  /** engine rev ≥ 11: every evaluated mode of the buffer (lossless / lossy) */
  modes?: { mode: string; comp_ratio: number; ratio_source: string; lossy: boolean; delta_mw: number; delta_mbs: number; selectable: boolean; skip_reason?: string | null }[]
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
  /** EXP-05: power budget this variant was explored with (spec value or previous-project reference) */
  power_budget?: { mw: number | null; source: string | null; reference_mw?: number } | null
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
  /** API ≥ 2026-10-09: IQ/performance-keeping optimum + near-optimal window vs lossy optimum */
  tiers?: Tiers
  /** tier A best total (compact copy for the run list view) */
  keep_total_mw?: number | null
  /** engine rev ≥ 11: per-lever effect, IQ-first greedy path and the design-space points */
  levers?: LeverAnalysis
  /** engine rev ≥ 11: every compression choice of the objective slice at the resolved DVFS levels */
  design_points?: DesignPoint[]
  /** timing judgement of the run (project review policy) */
  throughput_model?: 'stage' | 'pipelined'
  /** false = list-view row (run?view=summary): fetch archApi.runVariant for slices / buffers / options */
  detail?: boolean
}
// ---------------------------------------------------------------- lever analysis (engine rev ≥ 11)
/** neutral = keeps image quality (lossless SBWC) · eval = needs IQ evaluation (IP mode / knob) · trade = lossy */
export type IqClass = 'neutral' | 'eval' | 'trade'
export interface LeverDelta { total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; bw_mbs: number }
export interface LeverRow {
  key: string; kind: 'compression' | 'option'; label: string; iq: IqClass; confidence: string; note?: string | null
  buffer?: string; mode?: string; comp_ratio?: number | null
  /** vs baseline, this lever only */
  alone: LeverDelta | null
  /** at the end of the path: on vs off with every other chosen lever kept */
  in_context: LeverDelta | null; in_final?: boolean
  /** the buffer no longer exists with the final options (e.g. L0 skipped) */
  moot?: boolean; overlap: boolean
}
export interface LeverStep {
  phase: 'baseline' | IqClass; lever?: string; label: string; iq: IqClass; delta_mw: number; total_mw: number
  bw_mbs: number; delta_bw_mbs?: number; dropped?: string[] | null
}
export interface LeverMilestone { total_mw: number; bw_mbs: number; delta_mw: number; delta_pct: number | null; options: string[]; compression: Record<string, string> }
export interface LeverPoint {
  eligible?: boolean
  options: string[]; comp: Record<string, string>; iq: IqClass; total_mw: number; bw_mbs: number; cpu_mw: number; hw_mw: number; bw_mw: number
  /** API ≥ 2026-10-11 b: option item keys and the case key (base option set = a case of this run) */
  option_keys?: string[]; key?: string | null
}
export interface LeverRegisterBody {
  run_id: string; scenario_id: string; variant_id: string; compression: Record<string, string>; options: string[]
  iq_results: { option_key: string; status: 'adopted' | 'rejected'; note: string }[]; reason?: string; expected_project_ref?: string
}
export interface LeverRegisterResult {
  status: 'registered' | 'rejected'; rule?: string; case_key?: string; run_id?: string; rejected?: string[]; message?: string
  promoted: { id: string; total_mw: number }[]; skipped?: { variant_id: string; reason: string }[]
}
export interface LeverAnalysis {
  status: 'ok' | 'none'
  basis?: { statistic: string; runtime_scale: number; dvfs: string; sw_band_mw?: [number, number] | null }
  baseline?: LeverDelta
  levers?: LeverRow[]
  costs?: { key: string; label: string; delta_mw: number; speed_mhz: number; voltage_mv: number }[]
  steps?: LeverStep[]
  milestones?: Partial<Record<IqClass, LeverMilestone>>
  best_lever?: Partial<Record<IqClass, string | null>>
  points?: LeverPoint[]; point_count?: number
}
export interface DesignPoint {
  eligible?: boolean
  key?: string; comp: Record<string, string | null>; dvfs?: Record<string, number>
  total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; bw_ip_mw?: number; bw_cpu_mw?: number; bw_mbs: number; lossy: boolean; assumed: boolean
}

/** Every listable case of the variant (design points at the resolved DVFS + listed cases), split by IQ cost. */
export function caseGroups(v: VariantResult, withRaise: boolean): { keep: ExpCase[]; trade: ExpCase[] } {
  const b = v.baseline
  const fromPoint = (p: DesignPoint): ExpCase | null => (p.key ? {
    key: p.key, statistic: b.statistic, runtime_scale: b.runtime_scale, dvfs: p.dvfs ?? b.dvfs, dvfs_raise: 0,
    compression: Object.keys(p.comp), compression_modes: Object.fromEntries(Object.entries(p.comp).filter(([, m]) => m)) as Record<string, string>,
    total_mw: p.total_mw, cpu_mw: p.cpu_mw, hw_mw: p.hw_mw, bw_mw: p.bw_mw, bw_ip_mw: p.bw_ip_mw, bw_cpu_mw: p.bw_cpu_mw, bw_mbs: p.bw_mbs,
    lossy: p.lossy, assumed_ratio: p.assumed, verdict: b.verdict, eligible: p.eligible ?? b.eligible,
  } : null)
  const listed = [v.recommended, ...v.alternatives, ...(v.pareto ?? []), v.baseline, v.tiers?.keep?.best, v.tiers?.trade?.best]
  const seen = new Set<string>()
  const all: ExpCase[] = []
  for (const c of [...(v.design_points ?? []).map(fromPoint), ...listed]) {
    if (!c || seen.has(c.key) || (!withRaise && c.dvfs_raise > 0)) continue
    seen.add(c.key); all.push(c)
  }
  all.sort((x, y) => x.total_mw - y.total_mw || x.bw_mbs - y.bw_mbs)
  const trade = (c: ExpCase) => c.lossy && c.compression.length > 0
  return { keep: all.filter((c) => !trade(c)), trade: all.filter(trade) }
}

export const IQ_LABEL: Record<IqClass, string> = { neutral: '화질 무손실', eval: 'IQ 평가 필요', trade: '화질 trade (lossy)' }
export const IQ_COLOR: Record<IqClass, string> = { neutral: '#2F6F68', eval: '#B45309', trade: '#9B1C1C' }

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
  /** API ≥ 2026-10-09: set Δ minus the Δ of the always-beneficial (fixed) options alone; null = not a superset */
  effect_given_fixed?: number | null
}
/** Effect of adding one option to every set that lacks it (API ≥ 2026-10-09). */
export interface OptionMarginal {
  key: string; label: string; dimension: string; contexts: number; mean_mw: number; min_mw: number; max_mw: number
  always_beneficial: boolean; sign_varies: boolean; fixed: boolean
}
export interface TierWindow {
  best: ExpCase; near_pct: number; near_cases: number; near_mw: [number, number]; near_bw_mbs: [number, number]
  dvfs_range: Record<string, [number, number]>; compression_always: string[]; compression_optional: string[]
  /** evaluated cases inside the window (API ≥ 2026-10-09 b) */
  near_list?: { key: string; dvfs: Record<string, number>; compression: string[]; statistic: string; runtime_scale: number; total_mw: number; bw_mbs: number }[]
}
export interface Tiers { keep: TierWindow | null; trade: TierWindow | null; trade_gain: { delta_mw: number; delta_mbs: number; iq_risk: number } | null }
export interface PowerOptions {
  status: 'ok' | 'none' | 'skipped'; dimensions: OptionDimension[]; notes: string[]; sets: number; max_sets: number
  results: OptionResult[]; best: string | null; errors: { key: string; error: string }[]
  marginal?: OptionMarginal[]; fixed?: string[]
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
export interface RunDetail extends RunMeta { spec: Record<string, unknown>; variants: VariantResult[]; errors: VariantFailure[]; view?: 'full' | 'summary' }
export interface Power { total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; bw_ip_mw?: number; bw_cpu_mw?: number }
export interface BoardRow {
  id: string; scenario_id: string; variant_id: string; status: string; run_id: string; run_title: string | null; run_created_at: string | null
  case_key: string; selection_rule: string; selected_by: string; reason: string | null; created_at: string | null
  fps: number; power: Power; bw_mbs: number; distribution: Dist | null; compression: string[]; dvfs: Record<string, number>
  verdict: string; eligible_cases: number; alternatives: number; verified: Verified | null; statistic: Statistic; runtime_scale: number
  previous: { id: string; total_mw: number; delta_mw: number } | null
  power_options?: BoardOptions
  /** why the timing verdict (API ≥ verdict detail); derived = re-built from frozen stages of an older prediction */
  verdict_detail?: VerdictDetail | null
  /** API ≥ 2026-10-09: timing judgement the prediction was registered with ("stage" = before the review policy) */
  throughput_model?: 'stage' | 'pipelined'
  /** analysis condition of the registration (re-open in Timing Budget) */
  condition?: PredCondition
}
export interface PredCondition {
  applied_options?: { key: string; label: string }[]
  warmup_frames?: number
  source: 'timing-budget' | 'exploration'; statistic: string | null; runtime_scale: number | null; throughput_model: string; eis: string
  cpu_model: string; rt_margin: number | null; output_margin: number | null; config_profile_ref: string | null
  dvfs_overrides: Record<string, number>; dvfs: Record<string, number>; compression: string[]
  /** S5: explicit power params of the condition (absent = the profile's) */
  power_params_ref?: string | null
  /** S4: measurement used as input */
  measured?: { ref: string | null; inputs: { sw?: boolean; clock?: boolean; cpu?: boolean; measurement_ref?: string }; sw: string[]; clock_ref: string | null; cpu_ref: string | null }
}
export interface RecomputeResult { prediction_id: string; variant_id: string; scenario_id?: string; status: 'recomputed' | 'skipped'; reason?: string
  new_prediction_id?: string; old_total_mw?: number | null; new_total_mw?: number | null; delta_mw?: number | null }
/** Timing Budget URL params that re-create a registered condition (defaults left out). */
export function conditionParams(r: Pick<BoardRow, 'scenario_id' | 'variant_id' | 'condition'>): Record<string, string | undefined> {
  const c = r.condition
  const ov = Object.entries(c?.dvfs_overrides ?? {}).sort(([a], [b]) => a.localeCompare(b)).map(([d, l]) => `${d}:${l}`).join(',')
  const m = c?.rt_margin
  return {
    scenario: r.scenario_id, variant: r.variant_id,
    stat: c?.statistic && c.statistic !== 'max' ? c.statistic : undefined,
    scale: c?.runtime_scale !== null && c?.runtime_scale !== undefined && c.runtime_scale !== 1 ? String(c.runtime_scale) : undefined,
    eis: c?.eis && c.eis !== 'auto' ? c.eis : undefined,
    cpu: c?.cpu_model === 'profile' ? 'profile' : undefined,
    tp: c?.throughput_model === 'stage' || c?.throughput_model === 'pipelined' ? c.throughput_model : undefined,
    margin: m !== null && m !== undefined && Math.abs(m - 0.25) > 1e-9 ? String(Math.round(m * 100)) : undefined,
    cfg: c?.config_profile_ref ?? undefined,
    dvo: ov || undefined,
    pp: c?.power_params_ref ?? undefined,
    warmup: c?.warmup_frames ? String(c.warmup_frames) : undefined,
    mref: c?.measured?.ref ?? undefined,
    min: c?.measured?.ref ? (['sw', 'clock', 'cpu'] as const).filter((k) => c.measured!.inputs?.[k]).join(',') || undefined : undefined,
  }
}
export function conditionText(c: PredCondition | undefined): string {
  if (!c) return '—'
  const ov = Object.entries(c.dvfs_overrides).sort(([a], [b]) => a.localeCompare(b))
  return [`${c.source === 'timing-budget' ? 'TB' : '탐색'}`, `SW ${c.statistic ?? '?'} ×${c.runtime_scale ?? '?'}`, c.throughput_model === 'pipelined' ? 'pipeline' : 'stage',
    c.cpu_model === 'profile' ? 'CPU 측정' : null, ov.length ? `override ${ov.map(([d, l]) => `${d}:L${l}`).join(',')}` : null,
    c.measured?.sw?.length ? '실측 SW' : null, c.measured?.clock_ref ? '실측 clock' : null,
    c.power_params_ref ? `params ${c.power_params_ref}` : null,
    c.applied_options?.length ? c.applied_options.map((o) => o.label || o.key).join(' + ') : null].filter(Boolean).join(' · ')
}
export interface VerdictStage { id: string; name?: string; sw_ms?: number; hw_ms?: number; budget_ms?: number; overhead_ms?: number; margin?: number; feasible?: boolean; fill_pct?: number; throughput?: string; longest_sw_ms?: number; chain_ms?: number }
export interface VerdictDetail {
  status: 'ok' | 'clock_up' | 'fail' | string; reasons: string[]; nrt_clock_factor: number | null; derived: boolean
  stages: VerdictStage[]; intervals: Record<string, number>; period_ms: number | null
  latency?: Record<string, number | null> | null; statistic?: string | null; runtime_scale?: number | null
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
  /** CPU term of every case: flat assumption or the variant's measured CPU profile (EAS + growth) */
  cpu_model?: 'flat' | 'profile'
  /** EXP-05: customer budget — cases above it are not recommended (null = none) */
  power_budget_mw?: number | null; bw_budget_mbs?: number | null
  /** per variant: previous-project reference × (1 + tolerance) from the project review policy (tighter of the two) */
  budget_from_reference?: boolean
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
    ...(o.budget_from_reference ? { power_budget_from_reference: true } : {}),
    spec: {
      axes: { statistics: stats, runtime_scales: scales, dvfs_headroom_levels: o.dvfs_headroom_levels,
        compression: { enabled: o.modes.length > 0 && o.max_buffers > 0, modes: o.modes.length ? o.modes : ['lossy'], max_buffers: o.max_buffers, require_declared: o.require_declared },
        power_options: { enabled: o.options.knobs || o.options.modes, include_knobs: o.options.knobs, include_modes: o.options.modes, max_sets: o.options.max_sets } },
      constraints: { allow_lossy: o.allow_lossy,
        ...(o.power_budget_mw ? { power_budget_mw: o.power_budget_mw } : {}), ...(o.bw_budget_mbs ? { bw_budget_mbs: o.bw_budget_mbs } : {}) },
      objective: { statistic: o.objective_statistic, runtime_scale: o.objective_scale },
      ...(o.cpu_model === 'profile' ? { timing: { cpu_model: 'profile' } } : {}),
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
  /** list view: per-variant summary rows (~2 KB each); the full summary comes from runVariant on selection */
  run: (id: string) => send<RunDetail>('GET', `/arch/exploration/runs/${encodeURIComponent(id)}?view=summary`),
  runVariant: (id: string, scenarioId: string, variantId: string) =>
    send<VariantResult>('GET', `/arch/exploration/runs/${encodeURIComponent(id)}/variants/${encodeURIComponent(scenarioId)}/${encodeURIComponent(variantId)}`),
  createRun: (body: ReturnType<typeof runBody>) => send<RunDetail>('POST', '/arch/exploration/runs?view=summary', body),
  promote: (runId: string, variantIds?: string[], caseKey?: string, reason?: string, scenarioId?: string, expectedProject?: string) =>
    send<{ promoted: { id: string; variant_id: string; total_mw: number }[]; skipped: { variant_id: string; reason: string }[] }>(
      'POST', '/arch/predictions/promote', { run_id: runId, variant_ids: variantIds, case_key: caseKey, reason, scenario_id: scenarioId, expected_project_ref: expectedProject }),
  board: (scenarioId?: string, projectRef?: string) => send<{ rows: BoardRow[] }>('GET', `/arch/predictions/board${q({ scenario_id: scenarioId, project_ref: projectRef })}`),
  /** lever selector -> current prediction; options need IQ results (adopted) and are re-explored server side */
  registerLever: (body: LeverRegisterBody) => send<LeverRegisterResult>('POST', '/arch/predictions/lever', body),
  optionReviews: (scenarioId?: string) => send<OptionReview[]>('GET', `/arch/power-options/reviews${q({ scenario_id: scenarioId })}`),
  setOptionReview: (body: { scenario_id: string; variant_id?: string; option_key: string; status: ReviewStatus; note?: string }) =>
    send<OptionReview>('PUT', '/arch/power-options/reviews', body),
  /** S5: re-run a current prediction under its stored condition (optionally other power params) and register it */
  recompute: (predictionId: string, powerParamsRef?: string | null, reason?: string) =>
    send<RecomputeResult>('POST', `/arch/predictions/${encodeURIComponent(predictionId)}/recompute${q({ power_params_ref: powerParamsRef || undefined, reason: reason || undefined })}`),
  freshness: (scenarioId?: string, projectRef?: string) => send<Freshness>('GET', `/arch/predictions/freshness${q({ scenario_id: scenarioId, project_ref: projectRef })}`),
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

/** current prediction vs today's inputs (PRED-04) */
export interface FreshRow { prediction_id: string; scenario_id: string; variant_id: string; run_id?: string; status: 'fresh' | 'stale' | 'unknown'; reasons: string[]; changed: string[] }
export interface Freshness { rows: FreshRow[]; stale: number; fresh: number; engine_rev: string }
