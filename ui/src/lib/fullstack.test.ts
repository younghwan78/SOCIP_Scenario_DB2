import { describe, expect, it } from 'vitest'
import type { HandoffDoc, TimelineEvent } from './api'
import { buildTimeline, chainOf, frameSliceStyle, frameStarts, FULLSTACK_GROUPS, groupForNode, INDEPENDENT_STYLE, isFullStack, sliceColor } from './timeline'
import { cadenceRows } from '../pages/Behavior'

const ev = (task_id: string, layer: string, group: string, start: number, end: number, extra: Partial<TimelineEvent> = {}): TimelineEvent => ({
  task_id, logical_task_id: task_id.split('#')[0], layer, start_ms: start, end_ms: end,
  resource_name: `fullstack/${group}/${extra.process ?? 'p'} · ${extra.thread ?? 't'}`, ...extra,
})

// two frames of HAL request -> sensor (HW) -> EIS (HAL) -> MFC (HW), plus an own-cadence ABOX and a sibling branch
const events: TimelineEvent[] = [
  ev('hal.request#f0', 'hal', 'HAL', 0, 2, { frame_index: 0, thread: 'req' }),
  ev('sensor#f0', 'hw', 'HW', 2, 12, { frame_index: 0, node_id: 'sensor_rear', predecessors: ['hal.request#f0'], handoff: 'kick', thread: 'sensor' }),
  ev('eis#f0', 'hal', 'HAL', 13, 20, { frame_index: 0, node_id: 'eis', predecessors: ['sensor#f0'], handoff: 'complete', thread: 'vdis' }),
  ev('mfc#f0', 'hw', 'HW', 21, 28, { frame_index: 0, node_id: 'mfc_enc', predecessors: ['eis#f0'], handoff: 'kick', thread: 'mfc' }),
  ev('preview#f0', 'framework', 'FRAMEWORK', 21, 22, { frame_index: 0, predecessors: ['eis#f0'], handoff: 'ipc', thread: 'sf' }),
  ev('sensor#f1', 'hw', 'HW', 35.3, 45.3, { frame_index: 1, node_id: 'sensor_rear', thread: 'sensor' }),
  ev('abox#c0', 'hw', 'HW', 3, 3.8, { frame_index: null, node_id: 'abox', cadence_period_ms: 20, thread: 'abox' }),
  ev('abox#c1', 'hw', 'HW', 23, 23.8, { frame_index: null, node_id: 'abox', cadence_period_ms: 20, thread: 'abox' }),
]

describe('full-stack timeline', () => {
  const tl = buildTimeline(events, { maxFrames: 64, groupOrder: FULLSTACK_GROUPS })

  it('groups by layer in App → HW order and keeps hand-off kind on flows', () => {
    expect(isFullStack(events)).toBe(true)
    expect(isFullStack([{ task_id: 'a', start_ms: 0, end_ms: 1 }])).toBe(false)
    expect(tl.groups.map((g) => g.name)).toEqual(['FRAMEWORK', 'HAL', 'HW'])
    expect(tl.flows.find((f) => f.to === 'eis#f0')?.type).toBe('complete')
    const abox = tl.slices.find((s) => s.id === 'abox#c0')!
    expect(abox.layer).toBe('hw')
    expect(abox.period).toBe(20)
    expect(abox.frame).toBeNull()
  })

  it('frame flags start at HW work, not at the request issued frames earlier', () => {
    expect(frameStarts(tl)).toEqual([{ frame: 0, t: 2 }, { frame: 1, t: 35.3 }])
  })

  it('chainOf follows upstream and downstream transitively, not siblings of ancestors', () => {
    expect([...chainOf(tl, 'mfc#f0')].sort()).toEqual(['eis#f0', 'hal.request#f0', 'mfc#f0', 'sensor#f0'])
    expect([...chainOf(tl, 'sensor#f0')].sort()).toEqual(['eis#f0', 'hal.request#f0', 'mfc#f0', 'preview#f0', 'sensor#f0'])
  })

  it('cadence rows: declared own period, frame gap for frame-locked work, load per layer', () => {
    const rows = new Map(cadenceRows(tl).map((r) => [r.task, r]))
    const abox = rows.get('abox')!
    expect(abox.frameLocked).toBe(false)
    expect(abox.period).toBe(20)
    expect(abox.load).toBeCloseTo(0.8 * 50 / 10)   // HW duty %
    const sensor = rows.get('sensor')!
    expect(sensor.frameLocked).toBe(true)
    expect(sensor.period).toBeCloseTo(33.3)
    const eis = rows.get('eis')!                      // seen once: borrows the frame period
    expect(eis.period).toBeCloseTo(33.3)
    expect(eis.load).toBeCloseTo(7 * (1000 / 33.3))  // SW CPU ms/s
  })
})

describe('names shared with Pipeline timing', () => {
  const tl = buildTimeline(events, { maxFrames: 64, groupOrder: FULLSTACK_GROUPS })
  const slice = (id: string) => tl.slices.find((s) => s.id === id)!
  const track = (id: string) => tl.groups.flatMap((g) => g.tracks).find((t) => t.id === slice(id).track)!
  it('a slice shows its Pipeline node, else its common name, in capitals; the common name stays the key', () => {
    expect(slice('sensor#f0')).toMatchObject({ label: 'SENSOR_REAR', task: 'sensor' })
    expect(slice('hal.request#f0')).toMatchObject({ label: 'HAL_REQUEST', task: 'hal.request' })
    expect(cadenceRows(tl).find((r) => r.task === 'sensor')).toMatchObject({ name: 'SENSOR_REAR', track: 'SENSOR_REAR', trackSub: 'p · sensor' })
  })
  it('a HW track running one node takes its Pipeline name; other tracks show process, then thread', () => {
    expect(track('sensor#f0')).toMatchObject({ name: 'SENSOR_REAR', sub: 'p · sensor', context: 'p · sensor' })
    expect(track('abox#c0')).toMatchObject({ name: 'ABOX', sub: 'p' })
    expect(track('eis#f0')).toMatchObject({ name: 'p', sub: 'vdis' })
  })
  it('Pipeline timing slices carry the same name as their track', () => {
    const pl = buildTimeline([{ task_id: 'sensor_rear#f0', node_id: 'sensor_rear', task_type: 'hw', frame_index: 0, start_ms: 0, end_ms: 10 }])
    expect(pl.groups[0].tracks[0].name).toBe('SENSOR_REAR')
    expect(pl.slices[0].label).toBe('SENSOR_REAR')
  })
})

describe('cadence basis and full-stack colours', () => {
  const tl = buildTimeline(events, { maxFrames: 64, groupOrder: FULLSTACK_GROUPS })
  it('a hand-off document declares the loop; otherwise trace capture, frame gap or borrowed frame period', () => {
    const doc: HandoffDoc = { format: 'sdb.handoff/1', participants: [{ id: 'hal', layer: 'hal', name: 'hal' }],
      cadences: [{ id: 'frame', name: 'frame', kind: 'frame', period_ms: 33.3 }, { id: 'vdis', name: 'VDIS', kind: 'period', period_ms: 16.6 }],
      flows: [{ id: 'f', name: 'f', cadence: 'frame', steps: [{ to: 'hal', task: 'eis', cadence: 'vdis' }] }] }
    const plain = new Map(cadenceRows(tl).map((r) => [r.task, r]))
    expect([plain.get('abox')!.basis, plain.get('sensor')!.basis, plain.get('eis')!.basis]).toEqual(['trace', 'frame', 'borrowed'])
    const withDoc = new Map(cadenceRows(tl, doc).map((r) => [r.task, r]))
    expect(withDoc.get('eis')).toMatchObject({ basis: 'doc', period: 16.6, cadence: 'vdis', frameLocked: false })
  })
  it('layers get distinct colours; frame mode keeps HW deep and own-cadence work neutral', () => {
    expect(new Set(FULLSTACK_GROUPS.map((g) => sliceColor(g))).size).toBe(6)
    expect(frameSliceStyle(0, 'HW').fill).not.toBe(frameSliceStyle(0, 'HAL').fill)
    expect(frameSliceStyle(0, 'HAL').pattern).toBeNull()
    expect(INDEPENDENT_STYLE.pattern).toBe('m2m')
  })
})

describe('pipeline timing classification', () => {
  it('ABOX gets its own AUDIO group instead of falling into SW', () => {
    expect(groupForNode('abox', 'hw')).toBe('AUDIO')
    expect(groupForNode('mfc_enc', 'hw')).toBe('CODEC')
  })
})
