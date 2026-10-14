import { getJson, postJson } from './api'
import type { IpRow, TimingReport } from './timingBudget'

export interface WhatIfScope { project_ref: string; scenario_id: string; variant_id: string }
/** ``target`` names a server-registered change kind (``WhatIfTargets.change_kinds``); the editor is driven by that metadata. */
export interface WhatIfChange { target: string; anchor_id?: string; node_id?: string; stream_id?: string; param?: string; width?: number; height?: number; value?: number }
export interface ChangeKindMeta {
  target: string; label: string; shape: 'size' | 'value'; selector: 'anchor_id' | 'node_id' | 'stream_id' | null
  selector_optional: boolean; needs_param: boolean; unit: string; max_value: number | null; description: string
  /** instances available in this variant: id + size / value / ip / param */
  choices: { id: string; size?: [number, number]; value?: number | null; ip?: string | null; param?: string; label?: string; unit?: string; role?: string | null; primary?: boolean; where?: string[] }[]
}
export interface WhatIfTargets extends WhatIfScope {
  baseline_hash: string
  anchors: { id: string; size: [number, number]; kind: 'sensor' | 'output' | 'intermediate'; supported: boolean; role?: 'record' | 'preview' | null }[]
  nodes: { id: string; label: string; ip?: string | null; hw_name?: string; category?: string | null; size: [number, number]; size_supported: boolean; clock_supported: boolean }[]
  output_targets: string[]; supported_changes: string[]; limitations: string[]
  /** baseline FPS of the variant (API ≥ 2026-10-15) */
  fps?: number | null
  /** registry metadata of the change kinds offered for this variant (API ≥ 2026-10-15) */
  change_kinds?: ChangeKindMeta[]
  /** anchor-less scenarios (playback/call/game): surfaces grouped by size */
  streams?: { id: string; size: [number, number]; primary: boolean; where: string[] }[]
  capability?: { soc_ref: string | null; soc_profile: string; readiness: string | null; notes: string[] }
  soc_ref?: string | null
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
export interface PreviewRequest extends WhatIfScope { changes: WhatIfChange[]; expected_baseline_hash: string; config?: Record<string, unknown>; options?: Record<string, unknown> }
export interface WhatIfMetrics { modeled_power_mw: number; total_power_mw: number | null; cpu_power_mw: number; ip_power_mw: number; memory_power_mw: number; bw_mbs: number; fps: number; period_ms: number; feasible: boolean }
export interface WhatIfCoverage { complete: boolean; scope: string; missing_components: string[]; excluded_components: string[]; cpu_model: string; assumptions: string[] }
export interface WhatIfResult {
  baseline_hash: string; condition_hash: string; normalized_condition: { scope: WhatIfScope; changes: WhatIfChange[]; config: Record<string, unknown>; options: Record<string, unknown> }
  baseline: { report: TimingReport; metrics: WhatIfMetrics; coverage: WhatIfCoverage }; candidate: { report: TimingReport; metrics: WhatIfMetrics; coverage: WhatIfCoverage }
  delta: { metrics: Record<string, number | null>; ips: { node: string; required_clock_mhz: number; set_clock_mhz: number; power_mw: number; explanation: string }[] }
  warnings: string[]; model_lineage: Record<string, unknown>
}
export interface WhatIfExperiment {
  id: string; project_ref: string; scenario_id: string; variant_id: string; title: string; purpose: string | null; description: string | null; assumptions: string | null; conclusion: string | null
  query: string | null; visibility: 'private' | 'shared'; created_by: string; created_at: string; baseline_hash: string; condition_hash: string
  preview_request?: PreviewRequest; result?: WhatIfResult
}
export interface ExperimentDraft { title: string; purpose: string; description: string; assumptions: string; conclusion: string; visibility: 'private' | 'shared' }
const path = '/scenario-whatif'
export const whatIfApi = {
  targets: (scope: WhatIfScope) => getJson<WhatIfTargets>(`${path}/targets`, { ...scope }, false),
  plan: (scope: WhatIfScope, query: string) => postJson<WhatIfPlan>(`${path}/plan`, { ...scope, query }),
  preview: (body: PreviewRequest) => postJson<WhatIfResult>(`${path}/preview`, body),
  save: (previewRequest: PreviewRequest, result: WhatIfResult, draft: ExperimentDraft, query: string) => postJson<WhatIfExperiment>(`${path}/experiments`, { preview_request: previewRequest, expected_condition_hash: result.condition_hash, ...draft, query: query || null }),
  experiments: (scope: WhatIfScope, offset = 0) => getJson<{ items: WhatIfExperiment[]; total: number; limit: number; offset: number; has_next: boolean }>(`${path}/experiments`, { ...scope, limit: 20, offset }, false),
  experiment: (id: string) => getJson<WhatIfExperiment>(`${path}/experiments/${encodeURIComponent(id)}`, {}, false),
}
export const CHANGE_LABELS: Record<string, string> = { anchor_size: '크기 기준점', output_size: '출력 크기', node_size: 'IP 처리 크기', stream_size: '스트림 크기', fps: 'FPS', node_clock_mhz: 'IP clock 하한', node_param: 'IP 설정값' }
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
  if (kind.shape === 'size') return [change.width, change.height].every((size) => Number.isInteger(size) && Number(size) >= 16 && Number(size) <= 16384)
  return Number.isFinite(change.value) && Number(change.value) > 0 && (kind.max_value == null || Number(change.value) <= kind.max_value)
}

const sameTarget = (a: WhatIfChange, b: WhatIfChange) => a.target === b.target && (['anchor_id', 'node_id', 'stream_id', 'param'] as const).every((k) => (a[k] ?? '') === (b[k] ?? ''))
/** Add a change, replacing an existing one on the same target (one value per target, as the API requires). */
export function upsertChange(changes: WhatIfChange[], change: WhatIfChange): WhatIfChange[] {
  return changes.some((row) => sameTarget(row, change)) ? changes.map((row) => (sameTarget(row, change) ? change : row)) : [...changes, change]
}
/** "녹화 출력 record_out → 1920×1080" style one-line description of a change. */
export function describeChange(change: WhatIfChange): string {
  if (change.target === 'fps') return `FPS → ${change.value}`
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
