// Timeline events (measurement traces or simulation schedules) → Perfetto-like
// track groups, slices and flow arrows.
import type { TimelineEvent } from './api'

export interface Slice { id: string; track: string; group: string; start: number; end: number; label: string; frame: number | null; nodeId: string | null; kind: string }
export interface Track { id: string; group: string; name: string }
export interface TrackGroup { name: string; tracks: Track[] }
export interface Flow { from: string; to: string }
export interface Timeline { groups: TrackGroup[]; slices: Slice[]; flows: Flow[]; start: number; end: number; frames: number[] }

const RT = new Set(['csis', 'pdp', 'byrp', 'rgbp', 'yuvsc', 'mlsc'])
const NRT = new Set(['mtnr', 'msnr', 'yuvp', 'mcsc'])
const GROUP_ORDER = ['SENSOR', 'RT', 'NRT', 'M2M', 'CODEC', 'DISPLAY', 'SW', 'CONCURRENT']

export function groupForNode(node: string | null | undefined, kind: string | null | undefined, resource?: string | null): string {
  const n = String(node ?? resource ?? '').toLowerCase().replace(/^stage:/, '')
  if (kind === 'sw' || /^cpu|^storage|writer|rta|eis|crta/.test(n)) return 'SW'
  if (n.startsWith('sensor')) return 'SENSOR'
  if (RT.has(n)) return 'RT'
  if (NRT.has(n)) return 'NRT'
  if (/^(lme|gdc|vps)/.test(n)) return 'M2M'
  if (/^mfc|^apv|codec/.test(n)) return 'CODEC'
  if (/^dpu|^panel|display/.test(n)) return 'DISPLAY'
  return 'SW'
}

function trackOf(e: TimelineEvent): { group: string; name: string } {
  const parts = String(e.resource_name ?? '').split('/').map((s) => s.trim()).filter(Boolean)
  if (parts.length >= 3) return { group: parts[1].toUpperCase(), name: parts.slice(2).join(' / ') }
  const group = groupForNode(e.node_id, e.task_type, e.resource_id)
  const raw = e.node_id ?? e.hw_name ?? e.resource_id ?? e.logical_task_id ?? e.task_id
  return { group, name: String(raw).replace(/^stage:/, '').toUpperCase() }
}

function sliceLabel(e: TimelineEvent): string {
  const base = e.logical_task_id ?? e.node_id ?? e.hw_name ?? e.task_id
  return String(base).replace(/^stage:/, '').replace(/#f\d+$/, '')
}

export function buildTimeline(events: TimelineEvent[], opts: { maxFrames?: number } = {}): Timeline {
  const maxFrames = opts.maxFrames ?? 3
  const valid = events.filter((e) => Number.isFinite(e.start_ms) && Number.isFinite(e.end_ms) && e.end_ms >= e.start_ms)
  const framesToKeep = new Set([...new Set(valid.flatMap((e) => e.frame_index == null ? [] : [e.frame_index]))].sort((a, b) => a - b).slice(0, maxFrames))
  const kept = valid.filter((e) => e.frame_index == null || framesToKeep.has(e.frame_index))
  const trackMap = new Map<string, Track>()
  const slices: Slice[] = kept.map((e) => {
    const t = trackOf(e)
    const id = `${t.group}/${t.name}`
    if (!trackMap.has(id)) trackMap.set(id, { id, group: t.group, name: t.name })
    return { id: e.task_id, track: id, group: t.group, start: e.start_ms, end: e.end_ms,
      label: sliceLabel(e), frame: e.frame_index ?? null, nodeId: e.node_id ?? null, kind: String(e.task_type ?? '') }
  })
  const ids = new Set(slices.map((s) => s.id))
  const flows: Flow[] = []
  for (const e of kept) for (const p of e.predecessors ?? []) if (ids.has(p)) flows.push({ from: p, to: e.task_id })
  const groupsMap = new Map<string, Track[]>()
  for (const t of trackMap.values()) {
    if (!groupsMap.has(t.group)) groupsMap.set(t.group, [])
    groupsMap.get(t.group)!.push(t)
  }
  // Tracks keep first-seen order inside a group (pipeline order in traces).
  const order = (g: string) => { const i = GROUP_ORDER.indexOf(g); return i < 0 ? 50 : i }
  const groups = [...groupsMap.entries()].sort((a, b) => order(a[0]) - order(b[0])).map(([name, tracks]) => ({ name, tracks }))
  const start = slices.length ? Math.min(...slices.map((s) => s.start)) : 0
  const end = Math.max(start + 1, ...slices.map((s) => s.end))
  const frames = [...new Set(slices.map((s) => s.frame).filter((f): f is number => f !== null))].sort((a, b) => a - b)
  return { groups, slices, flows, start, end, frames }
}

/** Slices connected to a selection through flows (both directions, one hop). */
export function neighbours(tl: Timeline, sliceId: string): Set<string> {
  const out = new Set<string>([sliceId])
  for (const f of tl.flows) {
    if (f.from === sliceId) out.add(f.to)
    if (f.to === sliceId) out.add(f.from)
  }
  return out
}

export function frameStarts(tl: Timeline): { frame: number; t: number }[] {
  const firsts = new Map<number, number>()
  for (const s of tl.slices) if (s.frame !== null) firsts.set(s.frame, Math.min(firsts.get(s.frame) ?? Infinity, s.start))
  return [...firsts.entries()].sort((a, b) => a[0] - b[0]).map(([frame, t]) => ({ frame, t }))
}

const PALETTE: Record<string, string> = {
  SENSOR: '#B8C7D8', RT: '#F4B98C', NRT: '#F0A06B', M2M: '#E9B98E', CODEC: '#CDB6E3', DISPLAY: '#A7D6CC', SW: '#E7CF86', CONCURRENT: '#C9D3DE',
}
export function sliceColor(group: string): string { return PALETTE[group] ?? '#D8CFC2' }
