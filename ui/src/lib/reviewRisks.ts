// Project risk register (RPT-04): GET /review/risks, PATCH /review/risks/{id}.
import { getJson, requestJson } from './api'

export type Severity = 'critical' | 'high' | 'medium' | 'info'
export type RiskStatus = 'open' | 'watch' | 'mitigating' | 'accepted' | 'closed'
export interface Risk {
  id: string; label: string; seq: number; project_ref: string; key: string; rule: string
  severity: Severity; category: string; title: string; detail: string; affected: string[]; mitigation: string | null
  // RISK-01: confirmed · model_limit · input_unverified, and what to confirm first
  validity?: 'confirmed' | 'model_limit' | 'input_unverified' | null; checks?: string[]
  owner: string | null; status: RiskStatus; note: string | null; auto_state: 'active' | 'resolve_candidate' | 'manual'
  trend: string | null; first_seen_at: string | null; last_seen_at: string | null; updated_at: string | null; updated_by: string | null
  last_report_ref: string | null; history: { at: string; by: string | null; field: string; old: unknown; new: unknown }[]
}

export const risksApi = {
  list: (projectRef: string) => getJson<Risk[]>('/review/risks', { project_ref: projectRef }, false),
  update: (id: string, patch: { owner?: string; status?: RiskStatus; note?: string }) =>
    requestJson<Risk>('PATCH', `/review/risks/${encodeURIComponent(id)}`, patch),
}

export const SEVERITY_LABEL: Record<Severity, string> = { critical: 'Critical', high: 'High', medium: 'Medium', info: 'Info' }
export const SEVERITY_CLASS: Record<Severity, string> = { critical: 'v-fail', high: 'v-warn', medium: 'sev-med', info: '' }
export const STATUS_LABEL: Record<RiskStatus, string> = { open: 'Open', watch: 'Watch', mitigating: '대응 중', accepted: '수용', closed: '종료' }
export const SEVERITIES: Severity[] = ['critical', 'high', 'medium', 'info']

/** Open risks = not closed / accepted and not a resolve candidate (same rule as the API's risk_counts). */
export const isOpen = (r: Pick<Risk, 'status' | 'auto_state'>) => r.status !== 'closed' && r.status !== 'accepted' && r.auto_state !== 'resolve_candidate'
