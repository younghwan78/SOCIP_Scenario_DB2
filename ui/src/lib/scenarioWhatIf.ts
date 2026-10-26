import { getJson, postJson } from './api'
import type { IpRow, TimingReport } from './timingBudget'

export interface WhatIfScope { project_ref: string; scenario_id: string; variant_id: string }
/** ``target`` names a server-registered change kind (``WhatIfTargets.change_kinds``); the editor is driven by that metadata. */
export interface SensorBinding { catalog_ref: string; catalog_sha256: string; mode_label: string; lineup_ref: string; lineup_sha256: string; board_config: string; slot: string }
export interface WhatIfChange { target: string; anchor_id?: string; node_id?: string; stream_id?: string; param?: string; buffer_id?: string; option?: string; width?: number; height?: number; value?: number; domain?: string; level?: number; operation?: 'crop' | 'scale'; port?: string; x?: number; y?: number; sensor_binding?: SensorBinding }
export interface ModelEvidence { status?: string; source?: string; note?: string }
export interface GeometryCapability { min_size?: [number, number]; max_size?: [number, number]; alignment?: [number, number]; offset_alignment?: [number, number]; max_downscale?: number; max_upscale?: number; formats?: string[]; ports?: string[]; source?: string; status?: string }
export interface GeometryMeta { operations: ('crop' | 'scale')[]; default_operation?: 'crop' | 'scale'; capabilities: Partial<Record<'crop' | 'scale', GeometryCapability>> }
/** One selectable value of a "choice" lever (sensor mode · power option value · IP mode · compression mode). */
export interface LeverOption {
  id: string; label?: string; current?: boolean
  /** sensor_mode */
  ip_ref?: string; mode?: string; sensor?: string; place?: string | null; size?: [number, number]; fps?: number | null; bitwidth?: number | null; readout_ms?: number | null
  /** power_knob / ip_mode */
  iq_eval?: string | null; note?: string | null; explorable?: boolean; unit_power_mw_mp?: number | null; ppc?: number | null
  /** compression */
  ratio?: number; ratio_source?: string; lossy?: boolean; supported?: boolean | null; compressor?: string | null
  fps_compatible?: boolean; reason?: string | null; evidence?: ModelEvidence
  sensor_binding?: SensorBinding
}
export type LeverGroup = 'sensor' | 'size' | 'temporal' | 'clock' | 'mode' | 'compression' | 'other'
export interface ChangeKindMeta {
  target: string; label: string; shape: 'size' | 'value' | 'level' | 'choice'; selector: 'anchor_id' | 'node_id' | 'stream_id' | 'domain' | 'buffer_id' | 'param' | null
  selector_optional: boolean; needs_param: boolean; unit: string; max_value: number | null; description: string
  /** lever palette group · "required" = image-quality evaluation before adoption · compression accepts a ratio value (API ≥ 2026-10-16) */
  group?: LeverGroup; iq?: string | null; value_optional?: boolean
  /** instances available in this variant: id + size / value / ip / param */
  choices: { id: string; size?: [number, number]; value?: number | null; ip?: string | null; param?: string; label?: string; unit?: string; role?: string | null; primary?: boolean; where?: string[]
    /** dvfs_level: current level / clock, member IPs and the OPP ladder (slow -> fast) */
    level?: number | null; mhz?: number | null; ips?: string[]; ladder?: { level: number; mhz: number }[]
    /** choice levers: current value + options; chain_size: IPs that follow the size; history: node · ports */
    options?: LeverOption[]; current?: string | null; mode?: string; node_id?: string; downstream?: string[]; hint?: string
    node?: string; ports?: number; format?: string; family?: string; nodes?: string[]; declared?: string[]; llc?: boolean; history?: boolean
    readout_ms?: number | null; fps?: number | null; sensor?: string | null; hw_name?: string
    geometry?: GeometryMeta; affected_buffers?: string[]; evidence?: ModelEvidence }[]
}
export interface WhatIfTargets extends WhatIfScope {
  baseline_hash: string
  analysis_hash?: string
  baseline?: { metrics: WhatIfMetrics; coverage: WhatIfCoverage }
  model_lineage?: Record<string, unknown>
  anchors: { id: string; size: [number, number]; kind: 'sensor' | 'output' | 'intermediate'; supported: boolean; role?: 'record' | 'preview' | null }[]
  nodes: { id: string; label: string; ip?: string | null; hw_name?: string; category?: string | null; size: [number, number]; size_supported: boolean; clock_supported: boolean
    /** baseline applied clock and DVFS domain (API ≥ 2026-10-16) */
    clock_mhz?: number | null; dvfs_group?: string | null }[]
  output_targets: string[]; supported_changes: string[]; limitations: string[]
  /** baseline FPS of the variant (API ≥ 2026-10-15) */
  fps?: number | null
  /** registry metadata of the change kinds offered for this variant (API ≥ 2026-10-15) */
  change_kinds?: ChangeKindMeta[]
  /** anchor-less scenarios (playback/call/game): surfaces grouped by size */
  streams?: { id: string; size: [number, number]; primary: boolean; where: string[] }[]
  capability?: { soc_ref: string | null; soc_profile: string; readiness: string | null; notes: string[] }
  soc_ref?: string | null
  /** DVFS domains resolved by the baseline run (API ≥ 2026-10-16) */
  domains?: WhatIfDomain[]
  asks?: { ask: AskKind; label: string; description: string }[]
  /** in-house LLM for natural-language questions; unavailable = condition builder only */
  llm?: { available: boolean; model: string | null }
}
export interface WhatIfDomain { id: string; level: number; mhz: number; ips: string[]; stages: string[]; ladder: { level: number; mhz: number }[]; index: number }
export type AskKind = 'what_if' | 'combine' | 'search_limit' | 'diagnose'
export interface AskAction { label: string; ask: AskKind; search_domains?: string[] }
export interface WhatIfAnswer { verdict: 'ok' | 'fail' | 'info' | 'boundary'; headline: string; facts: string[]; actions: AskAction[] }
export interface SearchRow {
  domain: string; level: number; mhz: number; ips: string[]; at_min: boolean
  rows: { level: number; mhz: number; feasible: boolean; power_mw?: number; delta_mw?: number; min_slack_ms?: number; tight_stage?: string; reason: string | null }[]
  lowest: SearchRow['rows'][number] | null; first_fail: SearchRow['rows'][number] | null
}
export interface Diagnosis {
  verdict: string; reasons: string[]; notes: string[]; period_ms: number
  stages: { id: string; name: string; slack_ms: number; fill_pct?: number | null; hw_ms?: number; sw_ms?: number; budget_ms?: number }[]
  tight: Diagnosis['stages'][number] | null
  top_ips: { node: string; hw_ms: number; set_clock_mhz: number; required_clock_mhz: number; domain: string | null; level: number | null }[]
  domains: { id: string; level: number; mhz: number; down: number; up: number; ips: string[] }[]
}
export interface AskRequest extends WhatIfScope { basis_ref?: string; comparison?: 'retune' | 'fixed_opp'; query?: string; changes?: WhatIfChange[]; ask?: AskKind; search_domains?: string[]; combine?: CombineMode; config?: Record<string, unknown>; options?: Record<string, unknown>; expected_baseline_hash?: string; expected_analysis_hash?: string }
export type CombineMode = 'each' | 'factorial'
export interface CombineRow {
  key: string; levers: number[]; metrics: WhatIfMetrics | null
  delta: Record<'modeled_power_mw' | 'cpu_power_mw' | 'ip_power_mw' | 'memory_power_mw' | 'bw_mbs', number> | null
  feasible: boolean; min_slack_ms: number | null; tight_stage: string | null; reason: string | null; error?: boolean; notes: string[]
}
export interface CombineResult { mode: CombineMode; levers: { index: number; change: WhatIfChange; label: string; group: string; iq_required: boolean }[]; rows: CombineRow[]; best: string | null; interaction_mw: number | null; baseline_mw: number }
export interface AskResponse {
  scope: WhatIfScope; baseline_hash: string
  /** null = builder conditions (no interpretation) */
  interpretation: null | { status: 'ready' | 'clarification' | 'unsupported' | 'boundary' | 'llm_unavailable'; reason?: string; used?: 'llm'; model?: string | null; latency_ms?: number
    clarification?: { message: string; choices: { label: string; change: WhatIfChange }[] } | null; ignored?: { text: string; reason: string }[]; notes?: string[]; boundaries?: string[] }
  plan: null | { ask: AskKind; changes: WhatIfChange[]; search_domains: string[]; focus: FocusMetric[] }
  answer: WhatIfAnswer | null; result: WhatIfResult | null; search: SearchRow[] | null; diagnose: Diagnosis | null
  /** ask = combine (API ≥ 2026-10-16) */
  combine?: CombineResult | null
}
export type FocusMetric = 'power' | 'clock' | 'bw' | 'timing' | 'feasible'
export interface WhatIfClarification { field: string; message: string; source?: string; choices: { label: string; value: string; change?: WhatIfChange }[] }
export interface WhatIfPlan {
  /** partial = supported part interpreted, rest listed in ``ignored``; no_change = asked values equal the baseline */
  status: 'ready' | 'partial' | 'clarification' | 'unsupported' | 'no_change'
  query: string; changes: WhatIfChange[]; clarifications: WhatIfClarification[]; warnings: string[]; baseline_hash: string
  /** question text each change came from (same order as ``changes``) */
  sources?: string[]
  ignored?: { text: string; reason: string; hint: string | null }[]
  kept?: string[]; notes?: string[]; focus?: FocusMetric[]
}
export interface PreviewRequest extends WhatIfScope { basis_ref?: string; comparison?: 'retune' | 'fixed_opp'; changes: WhatIfChange[]; expected_baseline_hash: string; expected_analysis_hash?: string; config?: Record<string, unknown>; options?: Record<string, unknown> }
export type WhatIfSettings = Pick<PreviewRequest, 'config' | 'options' | 'basis_ref' | 'comparison'>
export interface WhatIfMetrics { modeled_power_mw: number; total_power_mw: number | null; cpu_power_mw: number; ip_power_mw: number; memory_power_mw: number; bw_mbs: number; fps: number; period_ms: number; feasible: boolean; sensor_power_mw?: number | null; latency_ms?: number | null }
export interface WhatIfCoverage { complete: boolean; scope: string; missing_components: string[]; excluded_components: string[]; cpu_model: string; assumptions: string[] }
export interface WhatIfResult {
  baseline_hash: string; analysis_hash?: string; condition_hash: string; normalized_condition: { scope: WhatIfScope; changes: WhatIfChange[]; comparison?: 'retune' | 'fixed_opp'; config: Record<string, unknown>; options: Record<string, unknown> }
  baseline: { report: TimingReport; metrics: WhatIfMetrics; coverage: WhatIfCoverage }; candidate: { report: TimingReport; metrics: WhatIfMetrics; coverage: WhatIfCoverage }
  delta: { metrics: Record<string, number | null>; ips: { node: string; required_clock_mhz: number; set_clock_mhz: number; power_mw: number; explanation: string }[] }
  warnings: string[]; model_lineage: Record<string, unknown>
  /** what a structural lever rewrote (sensor reshape, crop chain) · levers that need IQ evaluation (API ≥ 2026-10-16) */
  lever_notes?: string[]; iq_required?: string[]
}
export interface WhatIfExperiment {
  id: string; project_ref: string; scenario_id: string; variant_id: string; title: string; purpose: string | null; description: string | null; assumptions: string | null; conclusion: string | null
  query: string | null; visibility: 'private' | 'shared'; created_by: string; created_at: string; baseline_hash: string; condition_hash: string
  preview_request?: PreviewRequest; result?: WhatIfResult
}
export interface ExperimentDraft { title: string; purpose: string; description: string; assumptions: string; conclusion: string; visibility: 'private' | 'shared' }
export interface SweepConstraints { max_power_mw?: number; max_bw_mbs?: number; max_latency_ms?: number; min_slack_ms?: number; allow_iq_required: boolean }
export interface SweepRequest extends WhatIfScope { basis_ref?: string; config?: Record<string, unknown>; options?: Record<string, unknown>; expected_baseline_hash: string; expected_analysis_hash?: string; changes: WhatIfChange[]; axes: { label: string; values: WhatIfChange[] }[]; constraints: SweepConstraints; comparison: 'retune' | 'fixed_opp' }
export interface SweepRow { id: string; label: string; changes: WhatIfChange[]; preview_request?: PreviewRequest; metrics: WhatIfMetrics | null; delta: Record<string, number | null> | null; feasible: boolean; eligible: boolean; reasons: string[]; iq_required: string[]; condition_hash?: string; min_slack_ms: number | null; latency_ms: number | null }
export interface SweepResult { scope: WhatIfScope; baseline_hash: string; analysis_hash: string; comparison?: 'retune' | 'fixed_opp'; constraints?: SweepConstraints; baseline: { metrics: WhatIfMetrics; coverage: WhatIfCoverage }; rows: SweepRow[]; pareto_ids: string[]; best_id: string | null; total_cases: number; completed_cases: number; cancelled: boolean; assumptions: string[] }
export interface SweepJob { id: string; status: 'pending' | 'queued' | 'running' | 'completed' | 'cancelled' | 'interrupted' | 'failed'; completed_cases: number; total_cases: number; result?: SweepResult | null; error?: string | null; resumable: boolean; cancel_requested?: boolean }
const path = '/scenario-whatif'
export const whatIfApi = {
  targets: (scope: WhatIfScope, settings: WhatIfSettings = {}) => settings.config || settings.options || settings.basis_ref || settings.comparison
    ? postJson<WhatIfTargets>(`${path}/targets`, { ...scope, ...settings })
    : getJson<WhatIfTargets>(`${path}/targets`, { ...scope }, false),
  plan: (scope: WhatIfScope, query: string, settings: WhatIfSettings = {}) => postJson<WhatIfPlan>(`${path}/plan`, { ...scope, query, ...settings }),
  preview: (body: PreviewRequest) => postJson<WhatIfResult>(`${path}/preview`, body),
  /** builder conditions or a question (in-house LLM) -> executed answer */
  ask: (body: AskRequest) => postJson<AskResponse>(`${path}/ask`, body),
  save: (previewRequest: PreviewRequest, result: WhatIfResult, draft: ExperimentDraft, query: string) => postJson<WhatIfExperiment>(`${path}/experiments`, { preview_request: previewRequest, expected_condition_hash: result.condition_hash, ...draft, query: query || null }),
  experiments: (scope: WhatIfScope, offset = 0) => getJson<{ items: WhatIfExperiment[]; total: number; limit: number; offset: number; has_next: boolean }>(`${path}/experiments`, { ...scope, limit: 20, offset }, false),
  experiment: (id: string) => getJson<WhatIfExperiment>(`${path}/experiments/${encodeURIComponent(id)}`, {}, false),
  sweep: (body: SweepRequest) => postJson<SweepResult>(`${path}/sweeps`, body),
  startJob: (body: SweepRequest) => postJson<SweepJob>(`${path}/jobs`, body),
  job: (id: string) => getJson<SweepJob>(`${path}/jobs/${encodeURIComponent(id)}`, {}, false),
  cancelJob: (id: string) => postJson<SweepJob>(`${path}/jobs/${encodeURIComponent(id)}/cancel`, {}),
  resumeJob: (id: string) => postJson<SweepJob>(`${path}/jobs/${encodeURIComponent(id)}/resume`, {}),
}
export const CHANGE_LABELS: Record<string, string> = { anchor_size: '크기 기준점', output_size: '출력 크기', node_size: 'IP 처리 크기', stream_size: '스트림 크기', fps: 'FPS', node_clock_mhz: 'IP clock 하한', node_param: 'IP 설정값', dvfs_level: 'DVFS level',
  sensor_mode: '센서 변경', sensor_binding: '등록 센서 교체', chain_size: 'IP crop · downscale', power_knob: 'Power option', history_interval: 'Previous DMA 빈도', ip_mode: 'IP mode', compression: 'SBWC 압축' }
/** Lever palette: the commercialization tasks in the order a project usually tries them. */
export const LEVER_GROUPS: { id: LeverGroup; label: string; hint: string }[] = [
  { id: 'sensor', label: '센서', hint: '기존 예측 기준 sensor를 다른 sensor · mode로' },
  { id: 'size', label: '크기 · crop · downscale', hint: 'bayer crop · YUV downscale · MCSC 출력 크기' },
  { id: 'temporal', label: 'Temporal · previous DMA', hint: 'MTNR L0 skip 등 power option · previous DMA 빈도' },
  { id: 'clock', label: 'DVFS · clock · FPS', hint: 'domain level ±1~2 · IP clock 하한 · FPS' },
  { id: 'mode', label: 'IP mode', hint: 'IP 동작 mode (unit power · PPC)' },
  { id: 'compression', label: 'SBWC 압축', hint: 'on/off · lossless ↔ lossy · footprint mode' },
  { id: 'other', label: '기타', hint: '' },
]
const LEGACY_GROUP: Record<string, LeverGroup> = { output_size: 'size', anchor_size: 'size', node_size: 'size', stream_size: 'size', chain_size: 'size', fps: 'clock', node_clock_mhz: 'clock', dvfs_level: 'clock',
  sensor_mode: 'sensor', sensor_binding: 'sensor', power_knob: 'temporal', history_interval: 'temporal', ip_mode: 'mode', compression: 'compression' }
export const groupOf = (k: Pick<ChangeKindMeta, 'target' | 'group'>): LeverGroup => (k.group && k.group !== 'other' ? k.group : LEGACY_GROUP[k.target] ?? 'other')
/** Fallback metadata for API responses that predate ``change_kinds``. */
const LEGACY_KINDS: ChangeKindMeta[] = [
  { target: 'output_size', label: '출력 크기', shape: 'size', selector: 'anchor_id', selector_optional: true, needs_param: false, unit: '', max_value: null, description: '', choices: [] },
  { target: 'anchor_size', label: '크기 기준점', shape: 'size', selector: 'anchor_id', selector_optional: false, needs_param: false, unit: '', max_value: null, description: '', choices: [] },
  { target: 'node_size', label: 'IP 처리 크기', shape: 'size', selector: 'node_id', selector_optional: false, needs_param: false, unit: '', max_value: null, description: '', choices: [] },
  { target: 'fps', label: 'FPS', shape: 'value', selector: null, selector_optional: false, needs_param: false, unit: 'fps', max_value: 240, description: '', choices: [] },
  { target: 'node_clock_mhz', label: 'IP clock 하한', shape: 'value', selector: 'node_id', selector_optional: false, needs_param: false, unit: 'MHz', max_value: 5000, description: '', choices: [] },
]
/** Change kinds for a variant: the server registry when present, otherwise the legacy fixed set filled from targets. */
export function kindsOf(targets: WhatIfTargets | undefined): ChangeKindMeta[] {
  if (!targets) return []
  if (targets.change_kinds) return targets.change_kinds
  return LEGACY_KINDS.map((kind) => ({ ...kind, choices: kind.target === 'output_size' ? targets.output_targets.map((id) => ({ id, size: targets.anchors.find((a) => a.id === id)?.size }))
    : kind.target === 'anchor_size' ? targets.anchors.filter((a) => a.supported).map((a) => ({ id: a.id, size: a.size }))
      : kind.target === 'node_size' ? targets.nodes.filter((n) => n.size_supported).map((n) => ({ id: n.id, size: n.size }))
        : kind.target === 'node_clock_mhz' ? targets.nodes.filter((n) => n.clock_supported).map((n) => ({ id: n.id, ip: n.ip }))
          : [{ id: 'fps', value: targets.fps ?? null }] }))
}
export function clockExplanation(ip: Pick<IpRow, 'set_reason' | 'domain_leader' | 'clock_reason' | 'basis'>, fallback?: string): string {
  const reasons = { dvfs_floor: '최소 DVFS 단계 유지', dvfs_step: '필요 clock을 만족하는 DVFS 단계로 올림', domain: '공유 domain의 요구 clock 적용', exact: '요구값 적용' }
  const reason = ip.set_reason ? reasons[ip.set_reason] : ip.clock_reason ?? fallback ?? '기존 clock 모델로 계산'
  return `${reason}${ip.domain_leader ? ` · 기준 IP ${ip.domain_leader}` : ''}`
}
export function validChange(change: WhatIfChange, kinds: ChangeKindMeta[] = LEGACY_KINDS): boolean {
  const kind = kinds.find((k) => k.target === change.target) ?? LEGACY_KINDS.find((k) => k.target === change.target)
  if (!kind) return false
  if (kind.selector && !kind.selector_optional && !change[kind.selector]) return false
  if (kind.needs_param && !change.param) return false
  if (kind.shape === 'size') return !geometryError(change, kind)
  if (kind.shape === 'level') {
    const domain = kind.choices.find((c) => c.id === change.domain)
    return Number.isInteger(change.level) && (!domain?.ladder || domain.ladder.some((lv) => lv.level === change.level))
  }
  if (kind.shape === 'choice') {
    const sel = kind.selector ? change[kind.selector] : undefined
    const inst = kind.choices.find((c) => c.id === sel) ?? (kind.selector ? undefined : kind.choices[0])
    const opt = inst?.options?.find((o) => o.id === change.option)
    if (!change.option || (inst?.options && !opt) || opt?.supported === false) return false
    if (change.target === 'sensor_binding' && (!change.sensor_binding || !opt?.sensor_binding || Object.entries(opt.sensor_binding).some(([key, value]) => change.sensor_binding?.[key as keyof SensorBinding] !== value))) return false
    return change.value == null || (!!kind.value_optional && Number(change.value) > 0 && Number(change.value) <= 1)
  }
  return Number.isFinite(change.value) && (change.target !== 'history_interval' || Number.isInteger(change.value)) && Number(change.value) > 0 && (kind.max_value == null || Number(change.value) <= kind.max_value)
}

export function geometryError(change: WhatIfChange, kind: ChangeKindMeta): string | null {
  if (![change.width, change.height].every((size) => Number.isInteger(size) && Number(size) >= 16 && Number(size) <= 16384)) return '너비와 높이는 16–16384 사이의 정수여야 합니다.'
  const row = kind.selector ? kind.choices.find((c) => c.id === change[kind.selector!]) : undefined
  if (!row?.geometry) return null
  const operation = change.operation ?? row.geometry.default_operation ?? row.geometry.operations[0]
  if (!row.geometry.operations.includes(operation)) return '이 IP에서 지원하지 않는 크기 변경입니다.'
  const cap = row.geometry.capabilities[operation]
  if (!cap) return '지원 조건이 선언되지 않았습니다.'
  const output = [change.width!, change.height!]
  const min = cap.min_size ?? [16, 16], max = cap.max_size ?? row.size ?? [16384, 16384], alignment = cap.alignment ?? [1, 1]
  if (output.some((value, i) => value < min[i] || value > max[i])) return `지원 크기: ${min.join('×')}–${max.join('×')}`
  if (row.size && output.some((value, i) => value > row.size![i])) return '입력 크기보다 큰 출력은 지원하지 않습니다.'
  if (output.some((value, i) => value % alignment[i] !== 0)) return `크기를 ${alignment.join('×')} pixel 단위에 맞추세요.`
  if (change.port && !cap.ports?.includes(change.port)) return '지원하지 않는 출력 port입니다.'
  if ((cap.ports?.length ?? 0) > 1 && !change.port) return '변경할 출력 port를 선택하세요.'
  if (row.format && cap.formats?.length && !cap.formats.includes(row.format)) return '현재 입력 형식에서 지원하지 않는 크기 변경입니다.'
  if (operation === 'crop') {
    const offset = [change.x ?? 0, change.y ?? 0], step = cap.offset_alignment ?? alignment
    if (offset.some((value, i) => !Number.isInteger(value) || value < 0 || value % step[i] !== 0)) return `Crop 위치는 ${step.join('×')} pixel 단위의 0 이상 정수여야 합니다.`
    if (row.size && offset.some((value, i) => value + output[i] > row.size![i])) return 'Crop 영역이 입력 크기를 벗어납니다.'
  } else if (row.size) {
    if (change.x != null || change.y != null) return 'Crop 위치는 crop에서만 지정할 수 있습니다.'
    if (cap.max_downscale && output.some((value, i) => row.size![i] / value > cap.max_downscale!)) return `최대 축소 배율 ${cap.max_downscale}배를 넘습니다.`
    if (cap.max_upscale && output.some((value, i) => value / row.size![i] > cap.max_upscale!)) return `최대 확대 배율 ${cap.max_upscale}배를 넘습니다.`
  }
  return null
}
export function evidenceLabel(evidence?: ModelEvidence): string {
  const labels: Record<string, string> = { measured: '실측', calibrated: '실측 보정', verified: '검토됨', reviewed: '검토됨', borrowed: '차용 모델', assumed: '가정', synthetic: '합성 예제', unknown: '근거 미확인', unverified: '미검증', declared: '선언값', bound: 'Timing 근거 연결', missing_timing: 'Timing 근거 없음' }
  return evidence?.status ? labels[evidence.status] ?? evidence.status : '근거 미확인'
}
/** A sweep is a range of values of one existing typed condition, never executable free-form code. */
export function sweepValues(change: WhatIfChange, kind: ChangeKindMeta, raw: string): WhatIfChange[] {
  const tokens = raw.split(kind.shape === 'choice' ? /\n+/ : /[,;\n]+/).map((s) => s.trim()).filter(Boolean)
  if (tokens.length < 2 || tokens.length > 12) throw new Error('각 탐색 항목에는 2–12개 값을 입력하세요.')
  const values = tokens.map((token) => {
    let next: WhatIfChange
    if (kind.shape === 'size') {
      const dimensions = token.match(/^(\d+)\s*[x×]\s*(\d+)$/i)
      if (!dimensions) throw new Error('크기는 1920×1080 형식으로 입력하세요.')
      next = { ...change, width: Number(dimensions[1]), height: Number(dimensions[2]) }
    } else if (kind.shape === 'choice') {
      const instance = kind.selector ? kind.choices.find((row) => row.id === change[kind.selector!]) : kind.choices[0]
      const binding = instance?.options?.find((option) => option.id === token)?.sensor_binding
      next = { ...change, option: token, ...(kind.target === 'sensor_binding' ? { sensor_binding: binding } : {}) }
    }
    else if (kind.shape === 'level') next = { ...change, level: Number(token.replace(/^L/i, '')) }
    else next = { ...change, value: Number(token) }
    if (!validChange(next, [kind])) throw new Error(`지원 범위를 벗어난 값: ${token}`)
    return next
  })
  if (new Set(values.map((c) => JSON.stringify(c))).size !== values.length) throw new Error('같은 탐색 값을 중복 입력하지 마세요.')
  return values
}

const sameTarget = (a: WhatIfChange, b: WhatIfChange) => a.target === b.target && (['anchor_id', 'node_id', 'stream_id', 'param', 'domain', 'buffer_id'] as const).every((k) => (a[k] ?? '') === (b[k] ?? ''))
/** Add a change, replacing an existing one on the same target (one value per target, as the API requires). */
export function upsertChange(changes: WhatIfChange[], change: WhatIfChange): WhatIfChange[] {
  return changes.some((row) => sameTarget(row, change)) ? changes.map((row) => (sameTarget(row, change) ? change : row)) : [...changes, change]
}
/** "녹화 출력 record_out → 1920×1080" style one-line description of a change. */
export function describeChange(change: WhatIfChange): string {
  if (change.target === 'fps') return `FPS → ${change.value}`
  if (change.target === 'sensor_mode') return `센서 → ${change.option?.split('#').pop() ?? ''}`
  if (change.target === 'sensor_binding') return `${change.node_id} 센서 → ${change.sensor_binding?.catalog_ref ?? ''} · ${change.sensor_binding?.mode_label ?? change.option ?? ''}`
  if (change.target === 'chain_size') return `${change.node_id} ${change.operation ?? 'crop/downscale'}${change.operation === 'crop' ? ` (${change.x ?? 0}, ${change.y ?? 0})` : ''} → ${change.width}×${change.height}`
  if (change.target === 'power_knob') return `${change.param} → ${change.option}`
  if (change.target === 'history_interval') return `previous DMA ${change.buffer_id ?? '전체'} → ${change.value} frame마다`
  if (change.target === 'ip_mode') return `${change.node_id} mode → ${change.option}`
  if (change.target === 'compression') return `${change.buffer_id} → ${change.option}${change.value ? ` (×${change.value})` : ''}`
  if (change.target === 'dvfs_level') return `${change.domain} → L${change.level}`
  if (change.target === 'node_clock_mhz') return `${change.node_id} clock 하한 → ${change.value} MHz`
  if (change.value != null && change.width == null) return `${change.node_id ?? ''}${change.node_id ? ' ' : ''}${change.param ?? CHANGE_LABELS[change.target] ?? change.target} → ${change.value}`
  const where = change.target === 'node_size' ? `${change.node_id} 처리 크기` : change.target === 'stream_size' ? `스트림 ${change.stream_id}`
    : `${CHANGE_LABELS[change.target] ?? change.target} ${change.anchor_id ?? ''}`
  return `${where} → ${change.width}×${change.height}`
}
const pct = (a: number, b: number) => (a ? ` (${b - a >= 0 ? '+' : ''}${(((b - a) / a) * 100).toFixed(1)}%)` : '')
const signed = (v: number, digits = 1) => `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`
/** Answer lines for the question: the metrics it asked about first (power + feasibility when it named none). */
export function answerLines(result: WhatIfResult, focus: FocusMetric[] = []): { key: FocusMetric; text: string; warn?: boolean }[] {
  const keys: FocusMetric[] = focus.length ? [...focus] : ['power', 'feasible']
  if (!keys.includes('feasible')) keys.push('feasible')
  const b = result.baseline, c = result.candidate
  const lines: { key: FocusMetric; text: string; warn?: boolean }[] = []
  for (const key of keys) {
    if (key === 'power') {
      const [x, y] = [b.metrics.modeled_power_mw, c.metrics.modeled_power_mw]
      lines.push({ key, text: `모델 전력 ${x.toFixed(1)} → ${y.toFixed(1)} mW (${signed(y - x)} mW${x ? `, ${signed(((y - x) / x) * 100)}%` : ''}) · IP ${signed(c.metrics.ip_power_mw - b.metrics.ip_power_mw)} · 메모리 ${signed(c.metrics.memory_power_mw - b.metrics.memory_power_mw)} · CPU ${signed(c.metrics.cpu_power_mw - b.metrics.cpu_power_mw)} mW` })
    } else if (key === 'bw') {
      const [x, y] = [b.metrics.bw_mbs, c.metrics.bw_mbs]
      lines.push({ key, text: `BW ${x.toFixed(0)} → ${y.toFixed(0)} MB/s (${signed(y - x, 0)}${pct(x, y)})` })
    } else if (key === 'clock') {
      const base = new Map(b.report.ips.map((ip) => [ip.node, ip]))
      const moved = c.report.ips.map((ip) => ({ ip, d: ip.set_clock_mhz - (base.get(ip.node)?.set_clock_mhz ?? ip.set_clock_mhz) }))
        .filter((row) => Math.abs(row.d) >= 0.5).sort((p, q) => Math.abs(q.d) - Math.abs(p.d)).slice(0, 4)
      lines.push({ key, text: moved.length ? `적용 clock 변화: ${moved.map(({ ip, d }) => `${ip.node} ${(ip.set_clock_mhz - d).toFixed(0)}→${ip.set_clock_mhz.toFixed(0)} MHz`).join(' · ')}` : '적용 clock 변화 없음 (DVFS 단계 유지)' })
    } else if (key === 'timing') {
      const tight = (r: WhatIfResult['candidate']) => [...r.report.stages].sort((p, q) => (q.fill_pct ?? 0) - (p.fill_pct ?? 0))[0]
      const s0 = tight(b), s1 = tight(c)
      if (s1) lines.push({ key, warn: !s1.feasible, text: `가장 빠듯한 stage ${s1.name}: ${(s1.hw_ms + s1.sw_ms).toFixed(2)} / ${s1.budget_ms.toFixed(2)} ms (사용률 ${(s1.fill_pct ?? 0).toFixed(0)}%${s0 ? `, 기준 ${s0.name} ${(s0.fill_pct ?? 0).toFixed(0)}%` : ''}) · frame period ${b.metrics.period_ms.toFixed(2)} → ${c.metrics.period_ms.toFixed(2)} ms` })
    } else if (key === 'feasible') {
      lines.push({ key, warn: !c.metrics.feasible, text: c.metrics.feasible ? `처리량 조건 충족${b.metrics.feasible ? '' : ' (기준은 미달)'}` : `처리량 조건 미달 — ${c.report.verdict.reasons.join(' · ') || '사유 미상'}` })
    }
  }
  return lines
}

/** Crop / downscale presets: −n % of each axis aligned to 16 px (width) / 2 px (height). EIS 25→15 % ≈ −8 %. */
export function shrink(size: [number, number], pct: number): [number, number] {
  const f = 1 - pct / 100
  return [Math.max(16, Math.floor((size[0] * f) / 16) * 16), Math.max(16, Math.floor((size[1] * f) / 2) * 2)]
}
/** One default lever row per kind (the instance not yet used, prefilled with a value worth trying). */
export function defaultChange(kind: ChangeKindMeta, used: WhatIfChange[], fps?: number | null, clockOf?: (node: string) => number | null | undefined): WhatIfChange {
  const first = kind.choices.find((c) => !used.some((row) => row.target === kind.target && kind.selector && row[kind.selector] === c.id)) ?? kind.choices[0]
  const row: WhatIfChange = { target: kind.target }
  if (kind.selector && first && !(kind.selector_optional && kind.target === 'history_interval')) row[kind.selector] = first.id as never
  if (kind.needs_param && first?.param) row.param = first.param
  if (kind.shape === 'size') {
    const size = (first?.size ?? [1920, 1080]) as [number, number]
    ;[row.width, row.height] = kind.target === 'chain_size' ? shrink(size, 8) : size
    if (first?.geometry) {
      row.operation = first.geometry.default_operation ?? first.geometry.operations[0]
      const cap = first.geometry.capabilities[row.operation]
      const alignment = cap?.alignment ?? [1, 1]
      row.width = Math.max(cap?.min_size?.[0] ?? 16, Math.floor(row.width / alignment[0]) * alignment[0])
      row.height = Math.max(cap?.min_size?.[1] ?? 16, Math.floor(row.height / alignment[1]) * alignment[1])
      if (row.operation === 'crop') { row.x = 0; row.y = 0 }
      if (cap?.ports?.length === 1) row.port = cap.ports[0]
    }
  } else if (kind.shape === 'level') {
    const ladder = first?.ladder ?? [], at = ladder.findIndex((lv) => lv.level === first?.level)
    row.level = ladder[Math.max(0, at - 1)]?.level ?? first?.level ?? 0
  } else if (kind.shape === 'choice') {
    const opts = first?.options ?? []
    const cur = opts.find((o) => o.current)?.id ?? first?.current ?? first?.mode
    const option = opts.find((o) => o.id !== cur && o.supported !== false) ?? opts[0]
    row.option = option?.id
    if (option?.sensor_binding) row.sensor_binding = option.sensor_binding
  } else if (kind.target === 'history_interval') row.value = 2
  else row.value = first?.value ?? (kind.target === 'node_clock_mhz' ? (clockOf?.(String(first?.id)) ?? 400) : fps ?? 30)
  return row
}
/** "추천 레버 담기": one row per available commercialization lever (power options · history · SBWC lossless · DVFS −1), at most ``max``. */
export function suggestedLevers(kinds: ChangeKindMeta[], max = 5): WhatIfChange[] {
  const out: WhatIfChange[] = []
  const k = (t: string) => kinds.find((x) => x.target === t)
  for (const knob of k('power_knob')?.choices ?? []) { const opt = knob.options?.[0]; if (opt) out.push({ target: 'power_knob', param: knob.param ?? knob.id, option: opt.id }) }
  if (k('history_interval')?.choices.length) out.push({ target: 'history_interval', value: 2 })
  const sbwc = (k('compression')?.choices ?? []).find((b) => b.current === 'COMP_OFF' && b.history && b.options?.some((o) => !o.lossy && o.id !== 'COMP_OFF' && o.supported !== false))
  if (sbwc) out.push({ target: 'compression', buffer_id: sbwc.id, option: sbwc.options!.find((o) => !o.lossy && o.id !== 'COMP_OFF' && o.supported !== false)!.id })
  for (const d of k('dvfs_level')?.choices ?? []) {
    const ladder = d.ladder ?? [], at = ladder.findIndex((lv) => lv.level === d.level)
    if (at > 0) out.push({ target: 'dvfs_level', domain: d.id, level: ladder[at - 1].level })
  }
  return out.slice(0, max)
}
