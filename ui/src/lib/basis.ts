// 예측 기준 (model basis): config profile · power params · DVFS · engine bundle per 과제 (P1 registry, P2 promotion).
import { getJson, postJson } from './api'

export interface ModelBasis {
  id: string; project_ref: string; seq: number; code: string; title: string | null; status: 'draft' | 'active' | 'retired'
  config_profile_ref: string | null; power_params_ref: string | null; dvfs_table_ref: string | null; engine_rev: string
  content_hash: string; parent_ref: string | null; notes: string | null; created_by: string | null; created_at: string | null
  activated_by: string | null; activated_at: string | null
  /** "cfg simcfg-…-v2 · pmp v2 · dvfs-… · e11" */
  components: string
  trial?: TrialSummary
  existed?: boolean
}
export interface TrialSummary { total: number; done: number; skipped: number; failed: number; delta_mw_sum: number | null; delta_mw_min: number | null; delta_mw_max: number | null; started_at: string | null; promoted_at: string | null }
export interface TrialItem {
  prediction_id: string; scenario_id: string; variant_id: string; status: 'pending' | 'ok' | 'skipped' | 'error'
  old_total_mw: number | null; new_total_mw?: number | null; delta_mw?: number | null; run_id?: string; case_key?: string | null; rule?: string | null
  reason?: string; source?: string; tried_at?: string
}
export interface Trial { basis: ModelBasis; against: ModelBasis | null; diff: { field: string; from: string | null; to: string | null }[]; summary: TrialSummary; items: TrialItem[] }
export interface PromoteResult { basis: ModelBasis; promoted: { prediction_id: string; variant_id: string; new_prediction_id: string; delta_mw: number | null }[]; kept: { prediction_id: string; variant_id: string; reason: string }[] }

const enc = encodeURIComponent
export const basisApi = {
  list: (projectRef: string) => getJson<{ items: ModelBasis[]; active: ModelBasis | null }>('/bases', { project_ref: projectRef }, false),
  create: (body: { project_ref: string; config_profile_ref?: string | null; power_params_ref?: string | null; dvfs_table_ref?: string | null; title?: string; notes?: string; parent_ref?: string | null }) =>
    postJson<ModelBasis>('/bases', body),
  activate: (id: string) => postJson<ModelBasis>(`/bases/${enc(id)}/activate`, {}),
  retire: (id: string) => postJson<ModelBasis>(`/bases/${enc(id)}/retire`, {}),
  trial: (id: string) => getJson<Trial>(`/bases/${enc(id)}/trial`, {}, false),
  startTrial: (id: string) => postJson<Trial>(`/bases/${enc(id)}/trial`, {}),
  tryOne: (id: string, predictionId: string) => postJson<TrialItem>(`/bases/${enc(id)}/trial/${enc(predictionId)}`, {}),
  promote: (id: string, reason?: string) => postJson<PromoteResult>(`/bases/${enc(id)}/promote${reason ? `?reason=${enc(reason)}` : ''}`, {}),
}

export const FIELD_LABEL: Record<string, string> = { config_profile_ref: '설정 profile', power_params_ref: 'power params', dvfs_table_ref: 'DVFS table', engine_rev: 'engine' }
