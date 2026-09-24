// Variant condition helpers: KPI/mode classification, facets, reference diff.
// Rules follow dashboard/components/camera_review.py — explicit design
// conditions stay authoritative and ids never invent a missing KPI.
import type { Dict, Evidence, VariantRow } from './api'

export const MISSING = '—'

export function valueText(value: unknown): string {
  if (value === undefined || value === null || value === '') return MISSING
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const num = (v: unknown): number | null => {
  if (typeof v === 'boolean' || v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}
const enabled = (v: unknown): boolean => v === true || v === 1 || v === '1' || v === 'true'

export function kpiLabel(dc: Dict): string | null {
  const res = String(dc.resolution ?? '').toUpperCase().replace(/\s/g, '')
  const mapped = ({ '1920X1080': 'FHD', '3840X2160': 'UHD', '4K': 'UHD', '7680X4320': '8K' } as Record<string, string>)[res] ?? res
  const fps = num(dc.fps)
  if (!mapped || fps === null) return null
  return `${mapped}${fps}`
}

export const KPI_SET = ['FHD30', 'UHD30', 'FHD60', 'UHD60', '8K30'] as const
export type Mode = 'kpi' | 'pro' | 'slow' | 'portrait' | 'none'
export const MODE_LABEL: Record<Mode, string> = { kpi: 'KPI', pro: 'Pro Video', slow: 'Slow motion', portrait: 'Portrait video', none: 'None' }

/** Recording review mode. Capture/preview are always 'none'. */
export function recordingMode(v: Pick<VariantRow, 'scenario_id' | 'variant_id' | 'design_conditions'>): Mode {
  const dc = v.design_conditions ?? {}
  const identity = `${v.scenario_id} ${v.variant_id}`.toLowerCase().replace(/[-_]+/g, ' ')
  if (/\b(capture|preview)\b/.test(identity)) return 'none'
  const mode = ['camera_mode', 'subscenario', 'sensor_mode', 'is_scenario', 'extend_mode'].map((k) => String(dc[k] ?? '')).join(' ').toLowerCase().replace(/[-_]+/g, ' ')
  const text = `${mode} ${identity}`
  if (!/\b(recording|rec|video)\b/.test(text)) return 'none'
  if (enabled(dc.portrait) || /\b(portrait|bokeh)\b/.test(text)) return 'portrait'
  if (enabled(dc.pro_video) || /\bpro (video|mode)\b/.test(text) || enabled(dc.histogram)) return 'pro'
  const fps = num(dc.fps)
  if ((fps !== null && fps >= 120) || /\b(slow motion|slowmo|high speed|dualfps)\b/.test(text)) return 'slow'
  const kpi = kpiLabel(dc)
  if (kpi && (KPI_SET as readonly string[]).includes(kpi)) return 'kpi'
  return 'none'
}

export type Camera = 'rear_wide' | 'rear_tele' | 'rear_uw' | 'front' | 'dual'
export const CAMERA_LABEL: Record<Camera, string> = { rear_wide: 'Rear wide', rear_tele: 'Rear tele', rear_uw: 'Rear UW', front: 'Front', dual: 'Dual' }

/**
 * Camera facet from sensor placement. Rear tele / UW need a sensor-role map
 * (sensor_rear2 / sensor_rear3) that the fixtures do not declare yet, so a
 * plain "rear" is treated as the wide main camera.
 */
export function cameraOf(dc: Dict): Camera | null {
  const mode = String(dc.camera_mode ?? '').toLowerCase()
  const place = String(dc.sensor_place ?? '').toLowerCase()
  if (mode.startsWith('dual') || mode === 'triple' || place.includes('and') || dc.sensor_places) return 'dual'
  if (place === 'front') return 'front'
  if (place === 'rear_tele' || place === 'tele') return 'rear_tele'
  if (place === 'rear_uw' || place === 'uw' || place === 'ultrawide') return 'rear_uw'
  if (place === 'rear' || place === 'rear_wide') return 'rear_wide'
  return null
}

export function stabOf(dc: Dict): string {
  const s = dc.stabilization
  if (s === undefined || s === null || s === 0 || s === false || s === '0' || s === 'False') return 'None'
  return String(s)
}

export function conditionDistance(a: Dict, b: Dict): number {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)].filter((k) => !k.endsWith('_source')))
  let n = 0
  keys.forEach((k) => { if (valueText(a[k]) !== valueText(b[k])) n++ })
  return n
}

/** Variant closest to all others (non-derived first) — a natural baseline. */
export function medoidId(rows: VariantRow[]): string {
  const base = rows.filter((r) => !r.derived_from_variant)
  const pool = base.length ? base : rows
  let best = ''
  let bestScore = Infinity
  for (const r of [...pool].sort((x, y) => x.variant_id.localeCompare(y.variant_id))) {
    const score = pool.reduce((s, o) => s + conditionDistance(r.design_conditions, o.design_conditions), 0)
    if (score < bestScore) { best = r.variant_id; bestScore = score }
  }
  return best
}

/** Keys that differ from the baseline (parent for derived variants when present). */
export function changedKeys(row: VariantRow, reference: VariantRow | undefined, byId: Map<string, VariantRow>): string[] {
  const parent = row.derived_from_variant ? byId.get(row.derived_from_variant) : undefined
  const base = parent ?? reference
  if (!base || base.variant_id === row.variant_id) return []
  const keys = new Set([...Object.keys(row.design_conditions), ...Object.keys(base.design_conditions)].filter((k) => !k.endsWith('_source')))
  const diff = [...keys].filter((k) => valueText(row.design_conditions[k]) !== valueText(base.design_conditions[k]))
  const own = row.own_condition_keys ?? []
  return parent && own.length ? diff.filter((k) => own.includes(k)) : diff
}

export const PRIORITY_KEYS = ['resolution', 'fps', 'hdr', 'stabilization', 'camera_mode', 'sensor_place', 'codec_mfc', 'record_bitrate_mbps', 'extend_mode', 'portrait', 'subscenario']

export function varyingKeys(rows: VariantRow[]): { varying: string[]; constant: Record<string, string> } {
  const all = new Set<string>()
  rows.forEach((r) => Object.keys(r.design_conditions).forEach((k) => { if (!k.endsWith('_source')) all.add(k) }))
  const varying: string[] = []
  const constant: Record<string, string> = {}
  all.forEach((k) => {
    const vals = new Set(rows.map((r) => valueText(r.design_conditions[k])))
    if (vals.size > 1) varying.push(k)
    else constant[k] = [...vals][0]
  })
  const order = (k: string) => { const i = PRIORITY_KEYS.indexOf(k); return i < 0 ? 100 : i }
  varying.sort((a, b) => order(a) - order(b) || a.localeCompare(b))
  return { varying, constant }
}

export function shortLabels(ids: string[]): Record<string, string> {
  if (ids.length < 2) return Object.fromEntries(ids.map((i) => [i, i]))
  const parts = ids.map((i) => i.split('-'))
  let common = 0
  const minLen = Math.min(...parts.map((p) => p.length))
  while (common < minLen - 1 && parts.every((p) => p[common] === parts[0][common])) common++
  const out = Object.fromEntries(ids.map((i, n) => [i, parts[n].slice(common).join('-') || i]))
  return new Set(Object.values(out)).size === ids.length ? out : Object.fromEntries(ids.map((i) => [i, i]))
}

/** Normalized cross-scenario columns for the all-scenario matrix. */
export function matrixColumns(dc: Dict): Record<string, string> {
  const res = dc.resolution ? String(dc.resolution) : ''
  const fps = dc.fps ?? dc.target_fps ?? dc.panel_fps_hz
  const resFps = [res, fps !== undefined && fps !== null ? `${fps}fps` : ''].filter(Boolean).join(' · ') || MISSING
  const format = [dc.format, dc.extend_mode && dc.extend_mode !== 'EX_NONE' ? String(dc.extend_mode).replace(/^EX_/, '') : null, dc.capture_type, dc.call_type]
    .filter(Boolean).map(String).join(' · ')
  const out = [dc.output, dc.hdr].filter(Boolean).map(String).join(' · ')
  const cam = cameraOf(dc)
  const codec = [dc.codec_mfc ?? dc.codec, dc.record_bitrate_mbps ? `${dc.record_bitrate_mbps} Mbps` : null, dc.bitrate_mbps ? `${dc.bitrate_mbps} Mbps` : null]
    .filter(Boolean).map(String).join(' · ')
  const screen = dc.screen_on === undefined ? '' : (enabled(dc.screen_on) ? 'on' : 'off') + (dc.offload === undefined ? '' : enabled(dc.offload) ? ' · offload' : ' · CPU')
  return {
    'Res · fps': resFps,
    'Mode · Format': format || MISSING,
    'Output · HDR': out || MISSING,
    Stab: dc.stabilization === undefined ? MISSING : stabOf(dc),
    Camera: cam ? CAMERA_LABEL[cam] + (dc.camera_mode && dc.camera_mode !== 'single' ? ` · ${dc.camera_mode}` : '') : MISSING,
    'Codec · Rate': codec || MISSING,
    Screen: screen || MISSING,
  }
}

export type Source = 'measured' | 'calculated' | 'synthetic' | 'assumed'

export function evidenceSource(e: Pick<Evidence, 'id' | 'kind' | 'profiling_metadata' | 'provenance'>): Source {
  if (e.kind === 'evidence.simulation') return 'calculated'
  const scope = String((e.profiling_metadata as Dict | null | undefined)?.measurement_scope ?? '')
  const method = String((e.provenance as Dict | null | undefined)?.collection_method ?? '')
  const origin = String((e.provenance as Dict | null | undefined)?.data_origin ?? '')
  if (/synthetic/i.test(`${scope} ${method} ${origin} ${e.id}`)) return 'synthetic'
  return 'measured'
}

export function summaryText(dc: Dict): string {
  const kpi = kpiLabel(dc)
  const parts = [kpi, dc.hdr, stabOf(dc) !== 'None' ? stabOf(dc) : null, cameraOf(dc) ? CAMERA_LABEL[cameraOf(dc)!] : null,
    dc.record_bitrate_mbps ? `${dc.record_bitrate_mbps} Mbps` : null, dc.codec_mfc]
  return parts.filter(Boolean).map(String).join(' · ')
}
