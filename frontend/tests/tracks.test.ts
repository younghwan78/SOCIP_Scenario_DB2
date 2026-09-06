import { describe, expect, it } from 'vitest'
import { assignLanes, buildTracks } from '../src/engine/tracks'
import type { TimelineEvent } from '../src/engine/types'

function event(partial: Partial<TimelineEvent>): TimelineEvent {
  return { task_id: 'task', start_ms: 0, end_ms: 1, duration_ms: 1, ...partial }
}

describe('assignLanes', () => {
  it('keeps non-overlapping events in one lane', () => {
    const { placed, laneCount } = assignLanes([
      event({ task_id: 'a', start_ms: 0, end_ms: 5 }),
      event({ task_id: 'b', start_ms: 5, end_ms: 9 }),
    ])
    expect(laneCount).toBe(1)
    expect(placed.every((p) => p.lane === 0)).toBe(true)
  })

  it('splits overlapping events into lanes', () => {
    const { placed, laneCount } = assignLanes([
      event({ task_id: 'a', start_ms: 0, end_ms: 10 }),
      event({ task_id: 'b', start_ms: 4, end_ms: 8 }),
      event({ task_id: 'c', start_ms: 11, end_ms: 12 }),
    ])
    expect(laneCount).toBe(2)
    const byId = new Map(placed.map((p) => [p.event.task_id, p.lane]))
    expect(byId.get('a')).toBe(0)
    expect(byId.get('b')).toBe(1)
    expect(byId.get('c')).toBe(0)
  })
})

describe('buildTracks', () => {
  it('merges frames of the same OTF group onto one track', () => {
    const tracks = buildTracks([
      event({ task_id: 'isp#f0', otf_group_id: 'otf1#f0', frame_index: 0 }),
      event({ task_id: 'isp#f1', otf_group_id: 'otf1#f1', frame_index: 1, start_ms: 33, end_ms: 34 }),
    ])
    expect(tracks).toHaveLength(1)
    expect(tracks[0].id).toBe('track_otf_otf1')
    expect(tracks[0].placed).toHaveLength(2)
  })

  it('orders categories source -> OTF -> M2M -> SW -> sink', () => {
    const tracks = buildTracks([
      event({ task_id: 'disp', constraint_type: 'sink' }),
      event({ task_id: 'sw0', task_type: 'sw', resource_id: 'CPU0' }),
      event({ task_id: 'dma0', task_type: 'dma', resource_id: 'DMA0' }),
      event({ task_id: 'cam', constraint_type: 'source' }),
      event({ task_id: 'isp', otf_group_id: 'otf1' }),
    ])
    expect(tracks.map((t) => t.category)).toEqual(['sync_source', 'hw_otf', 'hw_m2m', 'sw', 'sync_sink'])
  })

  it('accumulates per-track busy time', () => {
    const tracks = buildTracks([
      event({ task_id: 'a#f0', task_type: 'dma', resource_id: 'DMA0', start_ms: 0, end_ms: 3.5 }),
      event({ task_id: 'a#f1', task_type: 'dma', resource_id: 'DMA0', start_ms: 10, end_ms: 12 }),
    ])
    expect(tracks[0].busyMs).toBeCloseTo(5.5)
  })

  it('groups SW tasks per resource', () => {
    const tracks = buildTracks([
      event({ task_id: 'sw_a#f0', task_type: 'sw', resource_id: 'CPU_BIG' }),
      event({ task_id: 'sw_b#f0', task_type: 'sw', resource_id: 'CPU_LITTLE' }),
    ])
    expect(tracks.map((t) => t.title).sort()).toEqual(['SW: CPU_BIG', 'SW: CPU_LITTLE'])
  })

  it('titles HW/SW tracks by node name, keeping the shared resource in parens', () => {
    const tracks = buildTracks([
      event({ task_id: 'n3aa#f0', node_id: 'n3aa', task_type: 'hw', resource_id: 'ISP' }),
      event({ task_id: 'gdc_m#f0', node_id: 'gdc_m', task_type: 'hw', resource_id: 'ISP', start_ms: 2, end_ms: 3 }),
      event({ task_id: 'eis#f0', node_id: 'eis', task_type: 'sw', resource_id: 'CPU_MID' }),
    ])
    const titles = tracks.map((t) => t.title).sort()
    // Same resource (ISP) still means separate per-node tracks.
    expect(titles).toEqual(['HW: gdc_m (ISP)', 'HW: n3aa (ISP)', 'SW: eis (CPU_MID)'])
  })

  it('titles OTF group tracks with the node chain instead of the group id', () => {
    const tracks = buildTracks([
      event({ task_id: 'sensor#f0', node_id: 'sensor_rear', otf_group_id: 'otf-0#f0', start_ms: 0, end_ms: 5 }),
      event({ task_id: 'csispdp#f0', node_id: 'csispdp', otf_group_id: 'otf-0#f0', start_ms: 1, end_ms: 6 }),
      event({ task_id: 'byrp#f0', node_id: 'byrp', otf_group_id: 'otf-0#f0', start_ms: 2, end_ms: 7 }),
      event({ task_id: 'rgbp#f0', node_id: 'rgbp', otf_group_id: 'otf-0#f0', start_ms: 3, end_ms: 8 }),
    ])
    expect(tracks).toHaveLength(1)
    expect(tracks[0].title).toBe('OTF: sensor_rear > ... > rgbp (4 IPs)')
  })
})
