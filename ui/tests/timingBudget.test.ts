import { afterEach, expect, it, vi } from 'vitest'
import { intervalOk, niceMax, nrtFactor, stageSegments, timingApi, verdictChip, type FleetRow, type StageRow } from '../src/lib/timingBudget'

afterEach(() => { vi.unstubAllGlobals() })

const nrt: StageRow = {
  id: 'nrt', name: 'NRT', nodes: ['mtnr'], sw_ms: 11.1, budget_ms: 22.23, hw_ms: 22.23, overhead_ms: 0, margin: 0.36, feasible: true, fill_pct: 100,
  sw_items: [
    { task: 'post_crta', kind: 'sw', runtime_ms: 0.5, latency_ms: 1.0, source: 'assumed', critical: true },
    { task: 'front_post_crta', kind: 'sw', runtime_ms: 0.5, latency_ms: 1.0, source: 'assumed', critical: false },
    { task: 'post_irta', kind: 'sw', runtime_ms: 5.6, latency_ms: 0, source: 'assumed', critical: true },
  ],
}

it('lays out a stage slot as latency → SW → HW and skips parallel (non-critical) chains', () => {
  const segs = stageSegments(nrt)
  expect(segs.map((s) => s.key)).toEqual(['lat:post_crta', 'sw:post_crta', 'sw:post_irta', 'hw'])
  expect(segs.reduce((a, s) => a + s.ms, 0)).toBeCloseTo(0.5 + 1.0 + 5.6 + 22.23)
})

it('RT slot is HW only', () => {
  const segs = stageSegments({ ...nrt, id: 'rt', name: 'RT', sw_items: [], hw_ms: 7.2, budget_ms: 25 })
  expect(segs).toHaveLength(1)
  expect(segs[0].ms).toBe(7.2)
})

it('checks intervals within ±tolerance of 1000/fps', () => {
  expect(intervalOk([33.333, 33.36], 33.333, 0.001)).toBe(true)
  expect(intervalOk([33.333, 33.4], 33.333, 0.001)).toBe(false)
})

it('computes NRT clock factor and verdict chips', () => {
  const row = { clocks: { nrt: { ip: 'mtnr', rule_mhz: 100, set_mhz: 150, level: null } } } as unknown as FleetRow
  expect(nrtFactor(row)).toBeCloseTo(1.5)
  expect(verdictChip('fail').cls).toBe('v-fail')
  expect(niceMax(420)).toBe(500)
})

it('posts timing-budget requests with options and surfaces API errors', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ report: { verdict: { status: 'ok' } } }) })
    .mockResolvedValueOnce({ ok: false, status: 422, statusText: 'Unprocessable', json: async () => ({ detail: 'unknown timeline task: x' }) })
  vi.stubGlobal('fetch', fetcher)
  await timingApi.variant('uc', 'v1', { statistic: 'mean', eis: 'off', runtime_scale: 1.2 })
  const [url, init] = fetcher.mock.calls[0]
  expect(url).toContain('/timing-budget/variant')
  expect(JSON.parse(init.body)).toEqual({ scenario_id: 'uc', variant_id: 'v1', options: { statistic: 'mean', eis: 'off', runtime_scale: 1.2 } })
  await expect(timingApi.fleet('uc', { statistic: 'max', eis: 'auto', runtime_scale: 1 })).rejects.toThrow(/unknown timeline task/)
})
