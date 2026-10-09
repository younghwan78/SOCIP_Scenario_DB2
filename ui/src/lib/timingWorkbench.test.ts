import { expect, it } from 'vitest'
import { autoLevel, runtimeScaleOf, dvfsDomains, formatOverrides, parseOverrides, type TimingReport } from './timingBudget'
import { conditionParams, conditionText, type BoardRow } from './archExplore'
import { detailLanes, outputPairs } from '../components/TimingCharts'
import { traceCondition } from '../pages/Pipeline'

it('round-trips DVFS overrides through the URL and drops junk', () => {
  expect(parseOverrides('CAM:3, INTCAM:2,bad,X:')).toEqual({ CAM: 3, INTCAM: 2 })
  expect(formatOverrides({ INTCAM: 2, CAM: 3 })).toBe('CAM:3,INTCAM:2')
  expect(formatOverrides({})).toBeUndefined()
})

const ladder = [{ level: 5, mhz: 200, mv: 600 }, { level: 3, mhz: 400, mv: 700 }, { level: 0, mhz: 800, mv: 800 }]
it('picks the slowest level meeting the required clock and flags an override below it', () => {
  expect(autoLevel(ladder, 350)?.level).toBe(3)
  expect(autoLevel(ladder, 900)).toBeNull()
  const r = { dvfs: { tables: ['CAM'], applied: true, ladders: { CAM: ladder }, overrides: { CAM: 5 } },
    ips: [{ node: 'csis', dvfs_group: 'CAM', required_clock_mhz: 350, dvfs_level: 5 }, { node: 'pdp', dvfs_group: 'CAM', required_clock_mhz: 120, dvfs_level: 5 }] } as unknown as TimingReport
  const [d] = dvfsDomains(r)
  expect(d.required_mhz).toBe(350)
  expect(d.auto?.level).toBe(3)
  expect(d.applied?.level).toBe(5)
  expect(d.below).toBe(true)
})

const rows = [
  { node: 'csis', type: 'hw', frame: 0, start_ms: 0, end_ms: 5, stage: 'rt' },
  { node: 'post_irta', type: 'sw', frame: 0, start_ms: 5, end_ms: 9, stage: 'nrt' },
  { node: 'mcsc', type: 'hw', frame: 0, start_ms: 9, end_ms: 14, stage: 'nrt' },
  { node: 'dpu', type: 'hw', frame: 0, start_ms: 20, end_ms: 22, stage: 'output' },
  { node: 'mfc_enc', type: 'hw', frame: 0, start_ms: 25, end_ms: 31, stage: 'output' },
  { node: 'dpu', type: 'hw', frame: 1, start_ms: 53, end_ms: 55, stage: 'output' },
] as never[]
it('lays out one lane per IP / SW task (SW before HW in a stage) and pairs preview / video outputs per frame', () => {
  const lanes = detailLanes(rows)
  expect(lanes.map((l) => l.id)).toEqual(['csis', 'post_irta', 'mcsc', 'dpu', 'mfc_enc'])
  expect(lanes.find((l) => l.id === 'post_irta')?.sw).toBe(true)
  expect(lanes.filter((l) => l.out).map((l) => l.id)).toEqual(['dpu', 'mfc_enc'])
  const pairs = outputPairs(rows, 33.3)
  expect(pairs[0]).toMatchObject({ frame: 0, delta_ms: 9, preview_lat_ms: 22, video_lat_ms: 31 })
  expect(pairs[1].video).toBeNull()
})

it('re-opens a registered condition in Timing Budget with non-default params only', () => {
  const row = { scenario_id: 's', variant_id: 'v', condition: { source: 'timing-budget', statistic: 'mean', runtime_scale: 1.2, throughput_model: 'pipelined', eis: 'auto',
    cpu_model: 'profile', rt_margin: 0.25, output_margin: 0.25, config_profile_ref: 'simcfg-a', dvfs_overrides: { INTCAM: 2, CAM: 3 }, dvfs: {}, compression: [] } } as unknown as BoardRow
  expect(conditionParams(row)).toEqual({ scenario: 's', variant: 'v', stat: 'mean', scale: '1.2', eis: undefined, cpu: 'profile', tp: 'pipelined',
    margin: undefined, cfg: 'simcfg-a', dvo: 'CAM:3,INTCAM:2', warmup: undefined, mref: undefined, min: undefined })
  expect(conditionText(row.condition)).toBe('TB · SW mean ×1.2 · pipeline · CPU 측정 · override CAM:L3,INTCAM:L2')
})

it('names the condition behind a Pipeline trace', () => {
  expect(traceCondition({ id: 'a', kind: 'evidence.simulation', run_info: { tool: 'scenariodb-timing-budget', timestamp: '2026-10-09T01:00:00Z', config_profile_ref: 'simcfg-a' } }).text)
    .toBe('Timing Budget 조건 · simcfg-a · 2026-10-09')
  expect(traceCondition({ id: 'b', kind: 'evidence.simulation', run_info: { tool: 'scenariodb-sim' } }).text).toBe('Simulate 기본 조건')
  expect(traceCondition({ id: 'c', kind: 'evidence.measurement', measured_at: '2026-06-14T00:00:00Z' }).text).toBe('실측 · 2026-06-14')
})

it('preserves custom growth when reopening a registered condition', () => {
  expect(runtimeScaleOf('1.05')).toBe(1.05)
  expect(runtimeScaleOf('0')).toBe(0)
  expect(runtimeScaleOf('-1')).toBe(1)
  expect(runtimeScaleOf('11')).toBe(1)
  expect(runtimeScaleOf(undefined)).toBe(1)
})
