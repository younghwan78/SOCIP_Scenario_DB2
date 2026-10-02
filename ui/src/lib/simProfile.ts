// Sim config profile selection (project-agreed run config: power model, power params, BW model).
// Default = the project's latest profile version, so a project that ships a v2 profile
// (e.g. Exynos2600 off-site: v2-vf + mif-linear + CPU topology) is what Timing / Explore use.
import { api } from './api'
import { useAsync } from './route'

export const NO_PROFILE = 'none'
export interface SimProfile { id: string; status?: string; version?: number }

export function pickProfile(profiles: SimProfile[], param: string | undefined): string | null {
  if (param === NO_PROFILE) return null
  if (param && profiles.some((p) => p.id === param)) return param
  return [...profiles].sort((a, b) => (b.version ?? 0) - (a.version ?? 0))[0]?.id ?? null
}

export function useSimProfiles(project: string, param: string | undefined): { profiles: SimProfile[]; ref: string | null; ready: boolean } {
  const q = useAsync(() => (project ? api.simConfigs(project).then((r) => r.items).catch(() => []) : Promise.resolve([] as SimProfile[])), [project])
  const profiles = q.data ?? []
  return { profiles, ref: pickProfile(profiles, param), ready: !q.loading }
}
