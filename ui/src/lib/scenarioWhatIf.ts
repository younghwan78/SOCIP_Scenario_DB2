import { getJson, postJson } from './api'
import type { IpRow, TimingReport } from './timingBudget'

export interface WhatIfScope { project_ref: string; scenario_id: string; variant_id: string }
export interface WhatIfChange { target: 'anchor_size' | 'node_size' | 'output_size' | 'fps' | 'node_clock_mhz'; anchor_id?: string; node_id?: string; width?: number; height?: number; value?: number }
export interface WhatIfTargets extends WhatIfScope {
  baseline_hash: string
  anchors: { id: string; size: [number, number]; kind: 'sensor' | 'output' | 'intermediate'; supported: boolean }[]
  nodes: { id: string; label: string; size: [number, number]; size_supported: boolean; clock_supported: boolean }[]
  output_targets: string[]; supported_changes: string[]; limitations: string[]
}
export interface WhatIfPlan { status: 'ready' | 'clarification' | 'unsupported'; query: string; changes: WhatIfChange[]; clarifications: { field: string; message: string; choices: { label: string; value: string }[] }[]; warnings: string[]; baseline_hash: string }
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
export const CHANGE_LABELS: Record<WhatIfChange['target'], string> = { anchor_size: '크기 기준점', output_size: '출력 크기', node_size: 'IP 처리 크기', fps: 'FPS', node_clock_mhz: 'IP clock 하한' }
export function clockExplanation(ip: Pick<IpRow, 'set_reason' | 'domain_leader' | 'clock_reason' | 'basis'>, fallback?: string): string {
  const reasons = { dvfs_floor: '최소 DVFS 단계 유지', dvfs_step: '필요 clock을 만족하는 DVFS 단계로 올림', domain: '공유 domain의 요구 clock 적용', exact: '요구값 적용' }
  const reason = ip.set_reason ? reasons[ip.set_reason] : ip.clock_reason ?? fallback ?? '기존 clock 모델로 계산'
  return `${reason}${ip.domain_leader ? ` · 기준 IP ${ip.domain_leader}` : ''}`
}
export function validChange(change: WhatIfChange): boolean {
  if (change.target === 'fps') return Number.isFinite(change.value) && Number(change.value) > 0 && Number(change.value) <= 240
  if (change.target === 'node_clock_mhz') return !!change.node_id && Number.isFinite(change.value) && Number(change.value) > 0 && Number(change.value) <= 5000
  return !!(change.target === 'node_size' ? change.node_id : change.anchor_id) && [change.width, change.height].every((size) => Number.isInteger(size) && Number(size) >= 16 && Number(size) <= 16384)
}
