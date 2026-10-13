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

/** GET /bases/{id}: the basis with its components' content (기준 상세 popover). */
export interface BasisDetail {
  basis: ModelBasis & { input_stamp?: Record<string, unknown> | null }
  parent: { id: string; code: string; status: string } | null
  inputs: { current: boolean; changed: string[]; engine_now: string }
  profile: null | { id: string; missing?: boolean; version?: number; status?: string; approved_by?: string | null; description?: string | null
    notes?: string | null; run_config?: Record<string, unknown>; rail_domains?: string[]; synthetic?: boolean }
  power_params: null | { ref: string; missing?: boolean; id?: string; version?: number; status?: string; soc_ref?: string; description?: string | null
    notes?: string | null; synthetic?: boolean
    model?: { ip_model?: string | null; ref_voltage_mv?: number | null; ref_fps?: number | null; ip_clock_power_fraction?: number | null; bw_model?: string | null }
    bw?: { mw_per_gbps?: number | null; read_mw_per_gbps?: number | null; write_mw_per_gbps?: number | null; llc_hit_scale?: number | null
      governor_util?: number | null; mif_opps: { mhz?: number; base_mw?: number; capacity_mbs?: number }[] }
    cpu?: { clusters: { name: string; core_type?: string; cores?: number; opps: number; max_mhz?: number | null; max_mv?: number | null
      max_mw_per_core?: number | null; leak_mw_per_core?: number | null }[]; source?: string | null }
    calibration?: { fit: boolean; ips: number; evidence: number } }
  dvfs: null | { id: string; missing?: boolean; version?: number; evt_hint?: string | null; scope?: string; source_revision?: string | null
    note?: string | null; synthetic?: boolean; domains?: { name: string; levels: number; min_mhz: number | null; max_mhz: number | null }[] }
  predictions: { current: number; ad_hoc: number; scenarios: number }
}

/** "dvfs-exynos2600-sample-v0" -> "sample-v0" (the SoC is the 과제's anyway). */
export function shortDvfs(ref: string | null | undefined): string {
  if (!ref) return 'DVFS 기본'
  return ref.replace(/^dvfs-/, '').replace(/^[a-z]+\d+[a-z]*-/i, '') || ref
}

/** Compact select / chip label: "B2 · cfg v2 · pmp v2 · sample-v0 · e11". */
export function basisShortLabel(b: Pick<ModelBasis, 'code' | 'components' | 'dvfs_table_ref'>): string {
  const parts = (b.components || '').split(' · ').map((p) => (b.dvfs_table_ref && p === b.dvfs_table_ref ? shortDvfs(p) : p))
    .map((p) => p.replace(/^cfg simcfg-.*-v(\d+)$/, 'cfg v$1'))
  return [b.code, ...parts].filter(Boolean).join(' · ')
}

/** basis_overrides key -> label */
export const OVERRIDE_LABEL: Record<string, string> = { config_profile: '설정 profile', power_params: 'power params', dvfs: 'DVFS table', config: '설정값 직접 변경 (DVFS override · 실측 입력 등)' }

const enc = encodeURIComponent
export const basisApi = {
  detail: (id: string) => getJson<BasisDetail>(`/bases/${enc(id)}`, {}, false),
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
