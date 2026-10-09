// Clock-domain residency (CPU cluster · DSU · GPU) — backend: src/scenario_db/api/services/clock_residency.py
import { getJson } from './api'

export interface ResBin { mhz: number; ratio: number }
export interface ResStats {
  bins: ResBin[]; mean_mhz: number; p50_mhz: number; max_mhz: number; min_mhz: number
  dominant_mhz: number; dominant_share: number
  /** share at ≥ 80 % of the max OPP; null when the domain's max OPP is unknown */
  high_share: number | null
}
export interface ClockNote { level: 'info' | 'warn'; code: string; text: string }
export interface DomainPower {
  dynamic_mw: number; static_mw: number; total_mw: number; ip_ref: string; sample: boolean; coeff_source?: string; notes: string[]
  at_fmax_mw: number; measured_mw: number | null; rails: string[]; delta_pct: number | null
}
export interface ClockDomain {
  domain_class: string; class_label: string; domain: string; is_dsu: boolean; opp_max_mhz: number | null
  wall: ResStats | null; active: ResStats | null
  active_ratio: number | null; clock_gated_ratio: number | null; power_gated_ratio: number | null
  pass_jsd: number | null; source: string | null; notes: ClockNote[]
  /** GPU / NPU power estimate from the residency (IP catalog power_model) vs measured rails */
  power?: DomainPower
}
export interface ClockView {
  rules_version: number; domains: ClockDomain[]; summary: string[]
  thresholds: { high_opp_fraction: number; high_opp_warn: number; pass_jsd_warn: number }
  /** PMU pass anchor stability (cpu.pass_cv) */
  pmu_pass?: { capture_cv: number | null; tasks: Record<string, number>; noisy: string[] } | null
}
export interface ClockRow {
  id: string; scenario_id: string; variant_id: string | null; measured_at: string | null; sw_baseline_ref: string | null; synthetic: boolean
  domains: { domain_class: string; class_label: string; domain: string; is_dsu: boolean; active_ratio: number | null; pass_jsd: number | null
    mean_mhz: number; high_share: number | null; basis: 'active' | 'wall'; warns: number; opp_max_mhz: number | null; power_mw?: number | null }[]
}

export const clockApi = {
  rows: (scenarioId?: string) => getJson<ClockRow[]>('/calibration/clock-residency', { scenario_id: scenarioId }, false),
}

export type Basis = 'active' | 'wall'

/** The distribution to show for a basis, falling back to the other one (with the basis actually used). */
export function pickStats(d: ClockDomain, basis: Basis): { s: ResStats | null; used: Basis } {
  if (basis === 'active' && d.active) return { s: d.active, used: 'active' }
  if (d.wall) return { s: d.wall, used: 'wall' }
  return { s: d.active, used: 'active' }
}

/** Sequential single hue (low → high frequency); same ramp as the report (reporting/clock_section.py). */
const LO = [0xd7, 0xec, 0xe7], HI = [0x17, 0x4d, 0x47]
export function oppColor(i: number, n: number): string {
  const t = n <= 1 ? 0 : i / (n - 1)
  return '#' + LO.map((a, k) => Math.round(a + (HI[k] - a) * t).toString(16).padStart(2, '0').toUpperCase()).join('')
}

/** Colour of one frequency: by its fraction of fmax when known (same colour = same headroom across
 *  domains), else by its rank among the bins. */
export function freqColor(mhz: number, fmax: number | null | undefined, i: number, n: number): string {
  if (fmax && fmax > 0) return oppColor(Math.round(Math.max(0, Math.min(1, mhz / fmax)) * 20), 21)
  return oppColor(i, n)
}

export function mhzText(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return v >= 1000 ? `${(v / 1000).toFixed(2)} GHz` : `${Math.round(v)} MHz`
}

export const pctText = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(d)}%`)

/** Weighted mean of bins (for client-side recomputation, e.g. a DSU table edit). */
export function meanMhz(bins: ResBin[]): number {
  const t = bins.reduce((a, b) => a + b.ratio, 0)
  return t > 0 ? bins.reduce((a, b) => a + b.mhz * b.ratio, 0) / t : 0
}

/** Domain order inside a class: CPU clusters, DSU, then other classes (GPU …). */
export function groupLabel(d: ClockDomain): string {
  return d.is_dsu ? 'DSU' : d.class_label
}
