// Sim config profile selection (project-agreed run config: power model, power params, BW model).
// Default = the project's latest profile version, so a project that ships a v2 profile
// (e.g. Exynos2600 off-site: v2-vf + mif-linear + CPU topology) is what Timing / Explore use.
import { api } from './api'
import { useAsync } from './route'
import { basisApi, type ModelBasis } from './basis'

export const NO_PROFILE = 'none'
export interface SimProfile {
  id: string; status?: string; version?: number
  /** API: what the profile is for (e.g. measurement-campaign baseline vs off-site full-feature) */
  description?: string | null; approved_by?: string | null
  run_config?: { power_model?: string | null; power_params_ref?: string | null; include_cpu_power?: boolean | null; asv_group?: number | null
    sw_margin?: number | null; bw_power_coeff?: number | null; vbat?: number | null; pmic_efficiency?: number | null; [k: string]: unknown }
}

/** Server default when a run names no power model (sim/power_model.py DEFAULT_POWER_MODEL_ID). */
export const DEFAULT_POWER_MODEL = 'v1-vfps'

/** Power params a run uses when the screen names none, as the server resolves it:
 * the basis' when it fixes one, else the chosen profile's (null = the power model's built-in coefficients). */
export function defaultPowerParams(basis: Pick<ModelBasis, 'power_params_ref'> | null | undefined, profile: SimProfile | undefined): string | null {
  return basis?.power_params_ref ?? profile?.run_config?.power_params_ref ?? null
}

/** Plain-language power model name (run_config.power_model). */
export const POWER_MODEL_LABEL: Record<string, string> = {
  'v1-vfps': 'v1-vfps · IP = unit power × MP × (V/710)² × fps/30, BW = mW per MB/s',
  'v2-vf': 'v2-vf · IP 동적(V²·f, clock gating) + leakage, BW = MIF 선형 모델',
}

/** URL value meaning "follow the 과제 active 예측 기준" (same as no cfg param). */
export const FOLLOW_BASIS = 'basis'

export function pickProfile(profiles: SimProfile[], param: string | undefined, basis?: ModelBasis | null): string | null {
  if (param === NO_PROFILE) return null
  if (param && param !== FOLLOW_BASIS) {
    if (profiles.some((p) => p.id === param)) return param
    throw new Error(`설정 profile을 찾을 수 없습니다: ${param}. profile을 다시 선택하세요.`)
  }
  // default: the active 예측 기준's profile (the server fills its power params / DVFS too), else the latest profile
  if (basis) return basis.config_profile_ref
  return [...profiles].sort((a, b) => (b.version ?? 0) - (a.version ?? 0))[0]?.id ?? null
}

export interface SimProfileSel {
  profiles: SimProfile[]; ref: string | null; ready: boolean; error: string | undefined
  /** the 과제's active 예측 기준 (null = none yet) */
  basis: ModelBasis | null
  /** true = the request follows the basis (no explicit profile choice); false = 기준 외 (ad-hoc, recorded as B?*) */
  followsBasis: boolean
}

export function useSimProfiles(project: string, param: string | undefined): SimProfileSel {
  const q = useAsync(() => (project ? api.simConfigs(project).then((r) => r.items) : Promise.resolve([] as SimProfile[])), [project])
  const bq = useAsync(() => (project ? basisApi.list(project).then((r) => r.active).catch(() => null) : Promise.resolve(null)), [project])
  const profiles = q.data ?? []
  const basis = bq.data ?? null
  let ref: string | null = null
  let error = q.error
  const loading = q.loading || bq.loading
  if (!loading && !error) {
    try { ref = pickProfile(profiles, param, basis) } catch (e) { error = e instanceof Error ? e.message : String(e) }
  }
  const followsBasis = !!basis && (!param || param === FOLLOW_BASIS || (param === basis.config_profile_ref))
  return { profiles, ref, ready: !loading && !error, error, basis, followsBasis }
}
