// Sim config profile selection (project-agreed run config: power model, power params, BW model).
// Default = the project's latest profile version, so a project that ships a v2 profile
// (e.g. Exynos2600 off-site: v2-vf + mif-linear + CPU topology) is what Timing / Explore use.
import { api } from './api'
import { useAsync } from './route'

export const NO_PROFILE = 'none'
export interface SimProfile { id: string; status?: string; version?: number }

export function pickProfile(profiles: SimProfile[], param: string | undefined): string | null {
  if (param === NO_PROFILE) return null
  if (param) {
    if (profiles.some((p) => p.id === param)) return param
    throw new Error(`설정 profile을 찾을 수 없습니다: ${param}. profile을 다시 선택하세요.`)
  }
  return [...profiles].sort((a, b) => (b.version ?? 0) - (a.version ?? 0))[0]?.id ?? null
}

export function useSimProfiles(project: string, param: string | undefined): { profiles: SimProfile[]; ref: string | null; ready: boolean; error: string | undefined } {
  const q = useAsync(() => (project ? api.simConfigs(project).then((r) => r.items) : Promise.resolve([] as SimProfile[])), [project])
  const profiles = q.data ?? []
  let ref: string | null = null
  let error = q.error
  if (!q.loading && !error) {
    try { ref = pickProfile(profiles, param) } catch (e) { error = e instanceof Error ? e.message : String(e) }
  }
  return { profiles, ref, ready: !q.loading && !error, error }
}
