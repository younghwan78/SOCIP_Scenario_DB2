// Memory power levers on a DMA path: compression (SBWC / AFBC), LLC residency, vOTF.
// One place decides "is it on" + the short label so diagram, tooltip and tables agree.
import type { Dict } from './api'

export const LEVER_COLOR = {
  llc: { line: '#15803D', fill: '#DCFCE7', text: '#14532D' },
  sbwc: { line: '#BE185D', fill: '#FCE7F3', text: '#831843' },
  votf: { line: '#0D9488', fill: '#CCFBF1', text: '#134E4A' },
} as const
export type LeverKey = keyof typeof LEVER_COLOR

const OFF = new Set(['', 'COMP_OFF', 'COMP_NONE', 'NONE', 'NO', 'OFF', 'DISABLE', 'DISABLED', 'FALSE', '0'])

export interface CompMode { comp_ratio?: number; typical_ratio?: number; compressor?: string }
export type CompCatalog = Record<string, CompMode>

export interface CompInfo {
  on: boolean
  mode: string
  /** compressor family: SBWC / AFBC / … */
  family: string
  lossy: boolean
  /** ratio applied to traffic (authored → SoC catalog comp_ratio); null = unknown */
  ratio: number | null
  typical: number | null
  /** short label for pills: "SBWC LL" / "SBWC lossy" */
  label: string
}

export function compInfo(mode: unknown, catalog?: CompCatalog | null, authoredRatio?: unknown): CompInfo {
  const m = String(mode ?? '').trim()
  const up = m.toUpperCase()
  if (OFF.has(up)) return { on: false, mode: m, family: '', lossy: false, ratio: 1, typical: null, label: '' }
  const cat = catalog?.[m] ?? catalog?.[up]
  const family = String(cat?.compressor ?? (/AFBC/.test(up) ? 'AFBC' : /SBWC|^COMP_(YUV|BAYER)_/.test(up) ? 'SBWC' : up.replace(/^COMP_/, '').split('_')[0] || 'COMP')).toUpperCase()
  const lossy = /LOSSY/.test(up)
  const ar = Number(authoredRatio)
  const ratio = Number.isFinite(ar) && ar > 0 ? ar : typeof cat?.comp_ratio === 'number' ? cat.comp_ratio : null
  return { on: true, mode: m, family, lossy, ratio, typical: typeof cat?.typical_ratio === 'number' ? cat.typical_ratio : null,
    label: `${family} ${lossy ? 'lossy' : /LOSSLESS/.test(up) ? 'LL' : ''}`.trim() }
}

export interface LlcInfo {
  on: boolean
  /** DRAM traffic factor while LLC-resident (1 = no saving / unknown) */
  weight: number
  weightKnown: boolean
  mb: number | null
  policy: string
  owner: string
  /** "LLC ×0.6" */
  label: string
}

export function llcInfo(placement: Dict | null | undefined): LlcInfo | null {
  if (!placement || placement.llc_allocated !== true) return null
  const w = Number(placement.llc_weight)
  const known = Number.isFinite(w) && w > 0 && w <= 1
  const mb = Number(placement.llc_allocation_mb)
  return {
    on: true, weight: known ? w : 1, weightKnown: known, mb: Number.isFinite(mb) && mb > 0 ? mb : null,
    policy: placement.llc_policy && placement.llc_policy !== 'none' ? String(placement.llc_policy) : '',
    owner: placement.allocation_owner ? String(placement.allocation_owner) : '',
    label: known ? `LLC ×${w}` : 'LLC',
  }
}

export function llcDetail(l: LlcInfo): string {
  return [l.mb ? `${l.mb} MB` : null, l.policy || null, l.owner ? `owner ${l.owner}` : null,
    l.weightKnown ? `DRAM ×${l.weight} (−${Math.round((1 - l.weight) * 100)}%)` : 'DRAM 효과 미정 (llc_weight 없음)'].filter(Boolean).join(' · ')
}

export function compDetail(c: CompInfo): string {
  if (!c.on) return 'off'
  return [c.mode, c.ratio !== null ? `ratio ${c.ratio} (BW 할당 기준)` : 'ratio 미정 → 무압축 상한', c.typical !== null ? `typ ${c.typical}` : null].filter(Boolean).join(' · ')
}

/** Small rounded label used in SVG diagrams. Returns the drawn width. */
export const pillWidth = (text: string, fs = 8.5) => Math.ceil(text.length * fs * 0.62) + 8
