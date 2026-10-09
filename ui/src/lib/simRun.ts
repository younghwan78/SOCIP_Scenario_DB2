// Preview-then-save for simulations (same flow as the Streamlit Evidence Dashboard "Confirm & Save Evidence"):
// a run is a preview (persist: false) until the user saves it; saving re-sends the identical request with
// persist: true with an expected params hash, so changed inputs cannot silently replace the preview. Identical requests by other
// users converge on one evidence row (deterministic id) — the response then says it already existed.
import { api, ApiError, invalidateCache, type SimRunRequest, type SimRunResponse } from './api'
import { pickProfile } from './simProfile'

export interface SimTarget { scenario: string; variant: string; project_id?: string | null; default_sw_profile_ref?: string | null }
export type SaveState = { status: 'saving' } | { status: 'saved'; evidence_id: string; existed: boolean } | { status: 'error'; error: string }
export type SimState =
  | { status: 'running' }
  | { status: 'done'; res: SimRunResponse; req: SimRunRequest; save?: SaveState }
  | { status: 'error'; error: string }

/** The request a preview run uses (and a save re-sends): project sim profile + default execution context. */
export async function simRequest(t: SimTarget, profileParam?: string): Promise<SimRunRequest> {
  const cfg = t.project_id ? pickProfile((await api.simConfigs(t.project_id)).items, profileParam) : null
  return {
    scenario_id: t.scenario, variant_id: t.variant, config_profile_ref: cfg ?? null,
    execution_context: { silicon_rev: 'EVT1', sw_baseline_ref: t.default_sw_profile_ref ?? 'sw-vendor-v1.2.3', thermal: 'nominal', method: 'calculation' },
  }
}

export async function runPreview(t: SimTarget, profileParam?: string): Promise<Extract<SimState, { status: 'done' }>> {
  const req = await simRequest(t, profileParam)
  const res = await api.simulate({ ...req, persist: false })
  return { status: 'done', res, req: { ...req, expected_params_hash: res.params_hash } }
}

/** Save a previewed run as simulation evidence. ``existed`` = the same inputs were already saved (by anyone). */
export async function saveResult(req: SimRunRequest): Promise<Extract<SaveState, { status: 'saved' }>> {
  if (!req.expected_params_hash) throw new Error('저장 확인 정보가 없습니다. Simulation을 다시 실행하세요.')
  let res: SimRunResponse
  try { res = await api.simulate({ ...req, persist: true }) } catch (e) {
    if (e instanceof ApiError && e.status === 409) throw new Error('입력·설정이 변경됐습니다. Simulation을 다시 실행한 뒤 저장하세요.')
    throw e
  }
  if (!res.persisted || res.params_hash !== req.expected_params_hash) throw new Error('미리보기와 동일한 결과의 저장을 확인하지 못했습니다. Simulation을 다시 실행하세요.')
  invalidateCache('/evidence')
  invalidateCache('/calibration')
  invalidateCache(`/scenarios/${encodeURIComponent(req.scenario_id)}`)
  return { status: 'saved', evidence_id: res.evidence_id, existed: !!res.cached }
}

/** True when the preview is already stored (the server matched a saved run with the same params hash). */
export const previewIsStored = (s: SimState | undefined) => s?.status === 'done' && !!s.res.persisted

export function saveLabel(s: SimState | undefined): string | null {
  if (s?.status !== 'done') return null
  if (s.res.persisted) return '저장됨 (같은 조건)'
  const v = s.save
  if (!v) return null
  if (v.status === 'saving') return '저장 중…'
  if (v.status === 'error') return `저장 실패: ${v.error}`
  return v.existed ? '이미 저장된 동일 결과' : '저장됨'
}
