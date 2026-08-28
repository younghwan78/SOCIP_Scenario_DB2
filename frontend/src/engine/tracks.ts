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
    const res = String(event.resource_id || 'CPU')
    return {
      id: `track_sw_${res}`,
      title: `SW: ${res}`,
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
    const res = String(event.resource_id || event.node_id || 'DMA')
    return {
      id: `track_m2m_${res}`,
      title: `M2M: ${res}`,
      category: 'hw_m2m',
      color: M2M_COLOR_FAMILIES[timelineGroupIndex(res, res) % M2M_COLOR_FAMILIES.length],
    }
  }
  const res = String(event.resource_id || event.node_id || 'HW')
  return { id: `track_hw_${res}`, title: `HW: ${res}`, category: 'misc', color: DEFAULT_COLOR }
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
    tracks.push({
      id: seed.id,
      title: seed.title,
      category: seed.category,
      color: seed.color,
      laneCount,
      placed,
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
