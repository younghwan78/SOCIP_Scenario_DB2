// Pure track-building: groups timeline events into resource-oriented tracks
// (Perfetto-style), merging frames of the same base task onto one track and
// resolving intra-track overlaps into lanes.
import { baseOtfGroupId, DEFAULT_COLOR, M2M_COLOR_FAMILIES, SINK_COLOR, SOURCE_COLOR, SW_COLOR_FAMILIES, timelineGroupIndex } from './colors'
import { OTF_COLOR_FAMILIES } from './colors'
import type { PlacedEvent, TimelineEvent, TrackCategory, TrackDefinition } from './types'
import { eventEnd, eventStart } from './types'

const CATEGORY_ORDER: Record<TrackCategory, number> = {
  sync_source: 0,
  hw_otf: 1,
  hw_m2m: 2,
  sw: 3,
  misc: 4,
  sync_sink: 5,
}

interface TrackSeed {
  id: string
  title: string
  category: TrackCategory
  color: string
  events: TimelineEvent[]
}

function classify(event: TimelineEvent): { id: string; title: string; category: TrackCategory; color: string } {
  if (event.constraint_type === 'source') {
    return { id: 'track_source', title: 'Sensor In', category: 'sync_source', color: SOURCE_COLOR }
  }
  if (event.constraint_type === 'sink') {
    return { id: 'track_sink', title: 'Display Out', category: 'sync_sink', color: SINK_COLOR }
  }
  const taskType = String(event.task_type ?? '').toLowerCase()
  if (taskType.includes('sw')) {
    // One track per SW task, named by the task; the shared processor
    // (resource_id, e.g. CPU_MID) rides along in parentheses.
    const res = String(event.resource_id || 'CPU')
    const name = String(event.node_id || res)
    return {
      id: `track_sw_${name}`,
      title: name === res ? `SW: ${res}` : `SW: ${name} (${res})`,
      category: 'sw',
      color: SW_COLOR_FAMILIES[timelineGroupIndex(res, res) % SW_COLOR_FAMILIES.length],
    }
  }
  const edgeType = String(event.edge_type ?? '').toLowerCase()
  const otfGroup = baseOtfGroupId(event.otf_group_id)
  if (otfGroup || edgeType.includes('otf')) {
    const group = otfGroup ?? 'OTF'
    const family = OTF_COLOR_FAMILIES[timelineGroupIndex(group, group) % OTF_COLOR_FAMILIES.length]
    return { id: `track_otf_${group}`, title: `OTF: ${group}`, category: 'hw_otf', color: family[0] }
  }
  if (taskType.includes('dma') || taskType.includes('m2m') || edgeType.includes('dma') || edgeType.includes('m2m')) {
    // Track per node (IP), colored by the shared resource so contention on
    // the same engine still reads as one color family.
    const res = String(event.resource_id || 'DMA')
    const name = String(event.node_id || res)
    return {
      id: `track_m2m_${name}`,
      title: name === res ? `M2M: ${res}` : `M2M: ${name} (${res})`,
      category: 'hw_m2m',
      color: M2M_COLOR_FAMILIES[timelineGroupIndex(res, res) % M2M_COLOR_FAMILIES.length],
    }
  }
  const res = String(event.resource_id || 'HW')
  const name = String(event.node_id || res)
  return {
    id: `track_hw_${name}`,
    title: name === res ? `HW: ${res}` : `HW: ${name} (${res})`,
    category: 'misc',
    color: DEFAULT_COLOR,
  }
}

// OTF streaming groups keep one track, but the title names the chain of
// pipeline nodes instead of the synthetic group id (otf-0, otf-1, ...).
function otfTrackTitle(seed: TrackSeed): string {
  const ordered = [...seed.events].sort((a, b) => eventStart(a) - eventStart(b))
  const nodes: string[] = []
  for (const event of ordered) {
    const name = String(event.node_id ?? '')
    if (name && !nodes.includes(name)) nodes.push(name)
  }
  if (!nodes.length) return seed.title
  if (nodes.length <= 3) return `OTF: ${nodes.join(' > ')}`
  return `OTF: ${nodes[0]} > ... > ${nodes[nodes.length - 1]} (${nodes.length} IPs)`
}

// Greedy interval-partitioning: earliest-start order, first lane whose last
// event ends at or before this event's start.
export function assignLanes(events: TimelineEvent[]): { placed: PlacedEvent[]; laneCount: number } {
  const sorted = [...events].sort((a, b) => eventStart(a) - eventStart(b) || eventEnd(a) - eventEnd(b))
  const laneEnds: number[] = []
  const placed: PlacedEvent[] = []
  const epsilon = 1e-9
  for (const event of sorted) {
    const start = eventStart(event)
    let lane = laneEnds.findIndex((end) => end <= start + epsilon)
    if (lane === -1) {
      lane = laneEnds.length
      laneEnds.push(eventEnd(event))
    } else {
      laneEnds[lane] = eventEnd(event)
    }
    placed.push({ event, lane })
  }
  return { placed, laneCount: Math.max(1, laneEnds.length) }
}

export function buildTracks(events: TimelineEvent[]): TrackDefinition[] {
  const seeds = new Map<string, TrackSeed>()
  for (const event of events) {
    const info = classify(event)
    let seed = seeds.get(info.id)
    if (!seed) {
      seed = { ...info, events: [] }
      seeds.set(info.id, seed)
    }
    seed.events.push(event)
  }

  const tracks: TrackDefinition[] = []
  for (const seed of seeds.values()) {
    const { placed, laneCount } = assignLanes(seed.events)
    const busyMs = seed.events.reduce((total, event) => total + Math.max(0, eventEnd(event) - eventStart(event)), 0)
    tracks.push({
      id: seed.id,
      title: seed.category === 'hw_otf' ? otfTrackTitle(seed) : seed.title,
      category: seed.category,
      color: seed.color,
      laneCount,
      placed,
      busyMs,
    })
  }

  tracks.sort((a, b) => {
    if (CATEGORY_ORDER[a.category] !== CATEGORY_ORDER[b.category]) {
      return CATEGORY_ORDER[a.category] - CATEGORY_ORDER[b.category]
    }
    return a.title.localeCompare(b.title)
  })
  return tracks
}
