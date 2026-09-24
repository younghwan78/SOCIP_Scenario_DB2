import { expect, it } from 'vitest'
import { buildTimeline } from '../src/lib/timeline'
import { analyse, frameOrigins } from '../src/lib/cadence'

it('limits frame count instead of treating frame IDs as zero-based indexes', () => {
  const tl = buildTimeline([100, 102, 109].map((frame) => ({ task_id: `f${frame}`, frame_index: frame, start_ms: frame * 10, end_ms: frame * 10 + 0.001 })), { maxFrames: 2 })
  expect(tl.frames).toEqual([100, 102])
  expect(tl.start).toBe(1000)
  expect(tl.slices[0].end - tl.slices[0].start).toBeCloseTo(0.001, 6)
})

it('excludes inverted timing instead of manufacturing a positive duration', () => {
  expect(buildTimeline([{ task_id: 'bad', start_ms: 10, end_ms: 9 }]).slices).toEqual([])
})

it('keeps distinct pipeline nodes separate even when they share a hardware name', () => {
  const tl = buildTimeline(['gdc_m', 'gdc_o'].map((node_id) => ({ task_id: node_id, node_id, hw_name: 'GDC', start_ms: 0, end_ms: 1 })))
  expect(tl.groups[0].tracks.map((t) => t.name)).toEqual(['GDC_M', 'GDC_O'])
})

it('requires a sensor and explicit flow for sensor-to-output latency', () => {
  const output = { task_id: 'out', node_id: 'panel', frame_index: 10, start_ms: 20, end_ms: 25 }
  const sensor = { task_id: 'in', node_id: 'sensor_rear', frame_index: 10, start_ms: 1, end_ms: 2 }
  const missing = buildTimeline([output])
  expect(frameOrigins(missing).size).toBe(0)
  const independent = analyse(buildTimeline([sensor, output]), undefined, 30)
  expect(independent.results.find((r) => r.stream.id === 'display')!.latencies).toEqual([])
  const linked = analyse(buildTimeline([sensor, { ...output, predecessors: ['in'] }]), undefined, 30)
  expect(linked.results.find((r) => r.stream.id === 'display')!.latencies).toEqual([24])
})

it('uses completion order for cadence even when frame numbers complete out of order', () => {
  const tl = buildTimeline([0, 1, 2].map((i) => ({ task_id: `out${i}`, node_id: 'panel', frame_index: [2, 1, 3][i], start_ms: i * 10, end_ms: i * 10 + 1 })))
  expect(analyse(tl, undefined, 100).results.find((r) => r.stream.id === 'display')!.intervals).toEqual([10, 10])
})
