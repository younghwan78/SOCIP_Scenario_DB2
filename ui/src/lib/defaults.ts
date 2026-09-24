// Review defaults agreed with the architecture team.
import type { Dict } from './api'

/** Scenario → reference ("기준") variant. Camera recording baseline = Rear(wide) UHD30 with EIS (SW VDIS). */
export const PREFERRED_REFERENCE: Record<string, string> = {
  'uc-camera-recording': 'cam-rec-r1-uhd30-vdis',
}

export function preferredReference(scenarioId: string | undefined, available: Iterable<string>, fallback: string): string {
  const want = scenarioId ? PREFERRED_REFERENCE[scenarioId] : undefined
  if (want) for (const v of available) if (v === want) return want
  return fallback
}

export const SEVERITY_RANK: Record<string, number> = { light: 1, medium: 2, heavy: 3, critical: 4 }

const RES_LINES: Record<string, number> = { SD: 480, HD: 720, FHD: 1080, QHD: 1440, UHD: 2160, '4K': 2160, '8K': 4320 }

/** Numeric resolution key for sorting: vertical lines (UHD → 2160, "3840x2160" → 2160). */
export function resolutionLines(v: unknown): number | null {
  if (v === undefined || v === null || v === '') return null
  const s = String(v).toUpperCase().replace(/\s/g, '')
  if (RES_LINES[s] !== undefined) return RES_LINES[s]
  const m = s.match(/(\d+)[X×](\d+)/)
  if (m) return Math.min(Number(m[1]), Number(m[2]))
  return null
}

export function resFpsKey(dc: Dict): number | null {
  const r = resolutionLines(dc.resolution)
  const f = Number(dc.fps ?? dc.target_fps ?? NaN)
  if (r === null && !Number.isFinite(f)) return null
  return (r ?? 0) * 10000 + (Number.isFinite(f) ? f : 0)
}
