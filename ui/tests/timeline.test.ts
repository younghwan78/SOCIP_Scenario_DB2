import { describe, expect, it } from 'vitest'
import events from './fixtures/trace-events.json'
import { buildTimeline, frameStarts, groupForNode, neighbours } from '../src/lib/timeline'
import { formatHash, parseHash } from '../src/lib/route'
import type { TimelineEvent } from '../src/lib/api'

describe('timeline', () => {
  const tl = buildTimeline(events as TimelineEvent[])
  it('groups tracks by resource path in pipeline order', () => {
    expect(tl.groups.map((g) => g.name).slice(0, 3)).toEqual(['SENSOR', 'RT', 'NRT'])
    expect(tl.groups.find((g) => g.name === 'RT')?.tracks.map((t) => t.name)).toEqual(['CSI', 'PDP', 'BYRP', 'RGBP', 'YUVSC', 'MLSC'])
  })
  it('builds flows from predecessors and finds neighbours', () => {
    expect(tl.flows.length).toBeGreaterThan(10)
    const mcsc = tl.slices.find((s) => s.nodeId === 'mcsc' && s.frame === 0)!
    const n = neighbours(tl, mcsc.id)
    expect([...n].some((id) => tl.slices.find((s) => s.id === id)?.nodeId === 'eis')).toBe(true)
  })
  it('lists frame starts', () => {
    expect(frameStarts(tl)[0]).toEqual({ frame: 0, t: 0 })
  })
  it('derives groups for simulation schedules without resource paths', () => {
    expect(groupForNode('mcsc', 'hw')).toBe('NRT')
    expect(groupForNode('stage:pre_me_rta', 'hw')).toBe('SW')
    expect(groupForNode('gdc_o', 'hw')).toBe('M2M')
    expect(groupForNode('mfc_enc', 'hw')).toBe('CODEC')
    const sim = buildTimeline([{ task_id: 'a#f0', node_id: 'csis', hw_name: 'CSIS', start_ms: 0, end_ms: 1, frame_index: 0, task_type: 'hw', predecessors: [] }])
    expect(sim.groups[0]).toMatchObject({ name: 'RT', tracks: [{ name: 'CSIS' }] })
  })
})

describe('route', () => {
  it('round-trips hash state', () => {
    const r = parseHash('#/compare?scenario=uc-camera-recording&variants=a,b')
    expect(r).toEqual({ page: 'compare', params: { scenario: 'uc-camera-recording', variants: 'a,b' } })
    expect(formatHash(r)).toBe('#/compare?scenario=uc-camera-recording&variants=a%2Cb')
    expect(parseHash('#/unknown').page).toBe('explorer')
  })
})
