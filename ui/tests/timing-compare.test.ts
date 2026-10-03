import { expect, it } from 'vitest'
import { buildTimeline } from '../src/lib/timeline'
import { compareTimelines, errTone, factorJson } from '../src/lib/timingCompare'

const ev = (scale: number) => Array.from({ length: 6 }, (_, f) => [['sensor_rear', 0, 27], ['csis', 0.2, 27], ['mtnr', 37, 9], ['eis', 50, 2]].map(([id, off, dur], i) => ({
  task_id: `${id}#${f}`, node_id: String(id), start_ms: f * 33.33 + Number(off) * (i > 1 ? scale : 1), end_ms: f * 33.33 + Number(off) * (i > 1 ? scale : 1) + Number(dur) * (i > 1 ? scale : 1), frame_index: f,
  task_type: id === 'eis' ? 'sw' : 'hw', predecessors: [] }))).flat()

it('aligns predicted vs measured per IP and lane', () => {
  const lane = (pid: string) => (pid === 'eis' ? 'sw' : pid === 'mtnr' ? 'nrt' : pid.startsWith('sensor') ? 'sensor' : 'rt')
  const c = compareTimelines(buildTimeline(ev(1.0)), buildTimeline(ev(1.2)), undefined, 30, lane)
  const mtnr = c.ips.find((d) => d.pid === 'mtnr')!
  expect(mtnr.dDurPct).toBeCloseTo(20, 1)
  expect(mtnr.factor).toBeCloseTo(1.2, 3)
  expect(mtnr.dStart).toBeGreaterThan(0)
  expect(c.ips.find((d) => d.pid === 'csis')!.dDurPct).toBeCloseTo(0, 6)
  expect(c.byLane.find((l) => l.lane === 'SW')!.d).toBeCloseTo(0.4, 6)
  expect(errTone(5)).toBe('v-ok'); expect(errTone(-20)).toBe('v-warn'); expect(errTone(40)).toBe('v-fail')
  expect(JSON.parse(factorJson(c, { predicted: 'p', measured: 'm' })).factors.mtnr).toBeCloseTo(1.2, 3)
})
