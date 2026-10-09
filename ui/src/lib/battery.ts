// Battery-side current: mA@Vbat = mW / Vbat / PMIC efficiency.
// Vbat and the efficiency come from the project's sim config profile (run_config.vbat / pmic_efficiency),
// so each project can change them; defaults 4.0 V · 0.85 (PMIC efficiency approximation).
import { api } from './api'
import { useAsync } from './route'
import { NO_PROFILE, pickProfile } from './simProfile'

export interface Battery { vbat: number; eff: number; source: string }
export const DEFAULT_BATTERY: Battery = { vbat: 4.0, eff: 0.85, source: '기본값' }

export function toMa(mw: number | null | undefined, b: Battery = DEFAULT_BATTERY): number | null {
  if (mw === null || mw === undefined || !Number.isFinite(mw) || b.vbat <= 0 || b.eff <= 0) return null
  return mw / b.vbat / b.eff
}

/** "≈ 368 mA" for a mW value (signed when ``signed``). */
export function maText(mw: number | null | undefined, b: Battery = DEFAULT_BATTERY, signed = false): string {
  const ma = toMa(mw, b)
  if (ma === null) return '—'
  const v = Math.abs(ma) >= 100 ? ma.toFixed(0) : ma.toFixed(1)
  return `${signed && ma >= 0 ? '+' : ''}${v} mA`
}

export const batteryNote = (b: Battery) => `mA@Vbat = mW ÷ ${b.vbat} V ÷ ${b.eff} (PMIC 효율 근사) · ${b.source}`

interface ProfileRow { id: string; version?: number; run_config?: { vbat?: number | null; pmic_efficiency?: number | null } }

export function batteryOf(profiles: ProfileRow[], ref: string | null): Battery {
  const p = profiles.find((x) => x.id === ref)
  const rc = p?.run_config ?? {}
  if (!p || (!rc.vbat && !rc.pmic_efficiency)) return DEFAULT_BATTERY
  return { vbat: rc.vbat || DEFAULT_BATTERY.vbat, eff: rc.pmic_efficiency || DEFAULT_BATTERY.eff, source: `${p.id}` }
}

/** Battery constants of the project's selected (or latest) sim config profile. */
export function useBattery(project: string | undefined, param?: string): Battery {
  const q = useAsync(() => (project ? api.simConfigs(project).then((r) => r.items as ProfileRow[]).catch(() => []) : Promise.resolve([] as ProfileRow[])), [project])
  const rows = q.data ?? []
  let ref: string | null = null
  try { ref = param === NO_PROFILE ? null : pickProfile(rows, param) } catch { ref = null }
  return batteryOf(rows, ref)
}
