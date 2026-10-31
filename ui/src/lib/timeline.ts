// Timeline events (measurement traces or simulation schedules) → Perfetto-like
// track groups, slices and flow arrows.
import type { TimelineEvent } from './api'

export interface Slice {
  id: string; track: string; group: string; start: number; end: number; label: string; frame: number | null; nodeId: string | null; kind: string
  /** common task name of the trace (sensor.readout): the key shared with hand-off documents; `label` is its display name */
  task: string
  /** full-stack traces: layer and own-cadence period (ms) */
  layer?: string | null; period?: number | null
}
/** name = what the row shows; sub = faint context after it; context = full-stack process · thread */
export interface Track { id: string; group: string; name: string; sub?: string; context?: string }
export interface TrackGroup { name: string; tracks: Track[] }
/** type = hand-off kind of the successor (kick | complete | ipc | irq | data), full-stack traces only */
export interface Flow { from: string; to: string; type?: string }
export interface Timeline { groups: TrackGroup[]; slices: Slice[]; flows: Flow[]; start: number; end: number; frames: number[] }

const RT = new Set(['csis', 'pdp', 'byrp', 'rgbp', 'yuvsc', 'mlsc'])
const NRT = new Set(['mtnr', 'msnr', 'yuvp', 'mcsc'])
const GROUP_ORDER = ['SENSOR', 'RT', 'NRT', 'M2M', 'CODEC', 'DISPLAY', 'AUDIO', 'SW', 'CONCURRENT']

export function groupForNode(node: string | null | undefined, kind: string | null | undefined, resource?: string | null): string {
  const n = String(node ?? resource ?? '').toLowerCase().replace(/^stage:/, '')
  if (kind === 'sw' || /^cpu|^storage|writer|rta|eis|crta/.test(n)) return 'SW'
  if (n.startsWith('sensor')) return 'SENSOR'
  if (RT.has(n)) return 'RT'
  if (NRT.has(n)) return 'NRT'
  if (/^(lme|gdc|vps)/.test(n)) return 'M2M'
  if (/^mfc|^apv|codec/.test(n)) return 'CODEC'
  if (/^dpu|^panel|display/.test(n)) return 'DISPLAY'
  if (/^abox|^audio/.test(n)) return 'AUDIO'
  return 'SW'
}

/** Name of a task in Pipeline timing and every Behavior view: the Pipeline node in capitals (SENSOR_REAR),
 *  else the common task name in the same form (hal.request → HAL_REQUEST). */
export const displayName = (raw: string) => raw.replace(/^stage:/, '').replace(/[.\s-]+/g, '_').toUpperCase()

function trackOf(e: TimelineEvent): { group: string; name: string; context?: string } {
  const parts = String(e.resource_name ?? '').split('/').map((s) => s.trim()).filter(Boolean)
  if (parts.length >= 3) return { group: parts[1].toUpperCase(), name: parts.slice(2).join(' / '), context: parts.slice(2).join(' / ') }
  const group = groupForNode(e.node_id, e.task_type, e.resource_id)
  const raw = e.node_id ?? e.hw_name ?? e.resource_id ?? e.logical_task_id ?? e.task_id
  return { group, name: displayName(String(raw)) }
}

function sliceTask(e: TimelineEvent): string {
  const base = e.logical_task_id ?? e.node_id ?? e.hw_name ?? e.task_id
  return String(base).replace(/^stage:/, '').replace(/#[fc]\d+(\.\d+)?$/, '')
}

/** Full-stack tracks are execution contexts (process · thread). A HW track running one Pipeline node takes the
 *  node's Pipeline name with the context after it (SENSOR_REAR  Sensor · rear readout); others show process, then thread. */
function nameContextTracks(tracks: Iterable<Track>, slices: Slice[]) {
  const nodes = new Map<string, Set<string | null>>()
  for (const s of slices) nodes.set(s.track, (nodes.get(s.track) ?? new Set()).add(s.nodeId))
  for (const t of tracks) {
    if (!t.context) continue
    const [proc, ...rest] = t.context.split(' · ')
    const thread = rest.join(' · ')
    const ns = [...(nodes.get(t.id) ?? [])]
    if (t.group === 'HW' && ns.length === 1 && ns[0]) {
      t.name = displayName(ns[0])
      t.sub = displayName(thread) === t.name ? proc : t.context
    } else {
      t.name = proc
      if (thread) t.sub = thread
    }
  }
}

/** Full-stack trace (events carry a `layer`): group order App → Framework → HAL → Kernel → FW → HW. */
export const FULLSTACK_GROUPS = ['APP', 'FRAMEWORK', 'HAL', 'KERNEL', 'FW', 'HW']
export const isFullStack = (events: TimelineEvent[] | null | undefined) => (events ?? []).some((e) => !!e.layer)

export function buildTimeline(events: TimelineEvent[], opts: { maxFrames?: number; groupOrder?: string[] } = {}): Timeline {
  const maxFrames = opts.maxFrames ?? 3
  const valid = events.filter((e) => Number.isFinite(e.start_ms) && Number.isFinite(e.end_ms) && e.end_ms >= e.start_ms)
  const framesToKeep = new Set([...new Set(valid.flatMap((e) => e.frame_index == null ? [] : [e.frame_index]))].sort((a, b) => a - b).slice(0, maxFrames))
  const kept = valid.filter((e) => e.frame_index == null || framesToKeep.has(e.frame_index))
  const trackMap = new Map<string, Track>()
  const slices: Slice[] = kept.map((e) => {
    const t = trackOf(e)
    const id = `${t.group}/${t.name}`
    if (!trackMap.has(id)) trackMap.set(id, { id, group: t.group, name: t.name, ...(t.context ? { context: t.context } : {}) })
    const task = sliceTask(e)
    const s: Slice = { id: e.task_id, track: id, group: t.group, start: e.start_ms, end: e.end_ms,
      label: displayName(e.node_id ?? task), task, frame: e.frame_index ?? null, nodeId: e.node_id ?? null, kind: String(e.task_type ?? '') }
    if (e.layer) { s.layer = e.layer; s.period = e.cadence_period_ms ?? e.independent_period_ms ?? null }
    return s
  })
  nameContextTracks(trackMap.values(), slices)
  const ids = new Set(slices.map((s) => s.id))
  const flows: Flow[] = []
  for (const e of kept) for (const p of e.predecessors ?? []) if (ids.has(p)) flows.push(e.handoff ? { from: p, to: e.task_id, type: e.handoff } : { from: p, to: e.task_id })
  const groupsMap = new Map<string, Track[]>()
  for (const t of trackMap.values()) {
    if (!groupsMap.has(t.group)) groupsMap.set(t.group, [])
    groupsMap.get(t.group)!.push(t)
  }
  // Tracks keep first-seen order inside a group (pipeline order in traces).
  const groupOrder = opts.groupOrder ?? GROUP_ORDER
  const order = (g: string) => { const i = groupOrder.indexOf(g); return i < 0 ? 50 : i }
  const groups = [...groupsMap.entries()].sort((a, b) => order(a[0]) - order(b[0])).map(([name, tracks]) => ({ name, tracks }))
  const start = slices.length ? Math.min(...slices.map((s) => s.start)) : 0
  const end = Math.max(start + 1, ...slices.map((s) => s.end))
  const frames = [...new Set(slices.map((s) => s.frame).filter((f): f is number => f !== null))].sort((a, b) => a - b)
  return { groups, slices, flows, start, end, frames }
}

/** Every slice upstream and downstream of a selection through flows (transitive; siblings are not included). */
export function chainOf(tl: Timeline, sliceId: string): Set<string> {
  const up = new Map<string, string[]>(), down = new Map<string, string[]>()
  for (const f of tl.flows) {
    up.set(f.to, [...(up.get(f.to) ?? []), f.from])
    down.set(f.from, [...(down.get(f.from) ?? []), f.to])
  }
  const out = new Set<string>([sliceId])
  for (const graph of [up, down]) {
    const stack = [sliceId]
    while (stack.length) for (const n of graph.get(stack.pop()!) ?? []) if (!out.has(n)) { out.add(n); stack.push(n) }
  }
  return out
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
  // full-stack traces: a frame starts on HW (sensor readout), not at its request issued frames earlier
  const fullStack = tl.slices.some((s) => s.layer === 'hw')
  const firsts = new Map<number, number>()
  for (const s of tl.slices) if (s.frame !== null && (!fullStack || s.layer === 'hw')) firsts.set(s.frame, Math.min(firsts.get(s.frame) ?? Infinity, s.start))
  return [...firsts.entries()].sort((a, b) => a[0] - b[0]).map(([frame, t]) => ({ frame, t }))
}

const PALETTE: Record<string, string> = {
  SENSOR: '#B8C7D8', RT: '#F4B98C', NRT: '#F0A06B', M2M: '#E9B98E', CODEC: '#CDB6E3', DISPLAY: '#A7D6CC', AUDIO: '#C8D9A8', SW: '#E7CF86', CONCURRENT: '#C9D3DE',
}
/** Full-stack layers: six well-separated hues (strong = labels, arrows, columns; fill = slices). */
export const LAYER_COLORS: Record<string, { strong: string; fill: string }> = {
  APP: { strong: '#7A5AF8', fill: '#D9CFFC' },
  FRAMEWORK: { strong: '#2D6FD2', fill: '#C3D8F6' },
  HAL: { strong: '#14917A', fill: '#B7E6D8' },
  KERNEL: { strong: '#C98A0B', fill: '#F5DDA0' },
  FW: { strong: '#C2417E', fill: '#F4C3DA' },
  HW: { strong: '#D2512A', fill: '#F6BFA8' },
}
export function sliceColor(group: string): string { return PALETTE[group] ?? LAYER_COLORS[group]?.fill ?? '#D8CFC2' }

// ---- frame × category coloring: hue = frame, lightness/pattern = RT / NRT / M2M / SW / output
export type SliceCat = 'SENSOR' | 'RT' | 'NRT' | 'M2M' | 'SW' | 'OUT'
/** Well-separated hues; consecutive frames never share a hue family. */
export const FRAME_HUES = [212, 26, 142, 278, 352, 186]
export function sliceCat(group: string): SliceCat {
  if (group === 'SENSOR' || group === 'RT' || group === 'NRT' || group === 'M2M') return group
  if (group === 'CODEC' || group === 'DISPLAY') return 'OUT'
  return 'SW'
}
export const CAT_LABEL: Record<SliceCat, string> = { SENSOR: 'Sensor', RT: 'RT', NRT: 'NRT', M2M: 'M2M', SW: 'SW (CPU)', OUT: 'Codec · Display' }
const SHADE: Record<SliceCat, { s: number; l: number; text: string }> = {
  SENSOR: { s: 18, l: 86, text: '#2B2F38' },
  RT: { s: 78, l: 47, text: '#FFFFFF' },
  NRT: { s: 62, l: 66, text: '#1F2430' },
  M2M: { s: 55, l: 80, text: '#1F2430' },
  OUT: { s: 30, l: 56, text: '#FFFFFF' },
  SW: { s: 40, l: 93, text: '#2B2F38' },
}
export interface SliceStyle { fill: string; stroke: string; text: string; pattern: 'm2m' | 'sw' | null; dash?: string }
export function frameHue(frame: number): number { return FRAME_HUES[((frame % FRAME_HUES.length) + FRAME_HUES.length) % FRAME_HUES.length] }
/** Own-cadence work in a full-stack trace when coloring by frame: it belongs to no frame. */
export const INDEPENDENT_STYLE: SliceStyle = { fill: '#DCD7CF', stroke: '#8C8574', text: '#2B2F38', pattern: 'm2m' }
export function frameSliceStyle(frame: number, group: string): SliceStyle {
  if (group in LAYER_COLORS) {
    // full-stack: hue = frame; HW deep, software layers mid-tone (the layer is already the row group)
    const h = frameHue(frame)
    return group === 'HW'
      ? { fill: `hsl(${h} 70% 48%)`, stroke: `hsl(${h} 60% 30%)`, text: '#FFFFFF', pattern: null }
      : { fill: `hsl(${h} 62% 76%)`, stroke: `hsl(${h} 55% 38%)`, text: '#1F2430', pattern: null }
  }
  const cat = sliceCat(group)
  const h = frameHue(frame)
  const sh = SHADE[cat]
  return {
    fill: `hsl(${h} ${sh.s}% ${sh.l}%)`,
    stroke: cat === 'SW' ? `hsl(${h} 55% 42%)` : `hsl(${h} 45% 34% / 0.55)`,
    text: sh.text,
    pattern: cat === 'M2M' ? 'm2m' : cat === 'SW' ? 'sw' : null,
    dash: cat === 'SW' ? '3 2' : undefined,
  }
}
