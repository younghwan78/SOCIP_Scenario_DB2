import { afterEach, expect, it, vi } from 'vitest'
import { DEFAULT_RUN, archApi, caseCount, caseDelta, levels, runBody, waterfall, type Attribution, type ExpCase } from '../src/lib/archExplore'
import { parseHash } from '../src/lib/route'

afterEach(() => { vi.unstubAllGlobals() })

it('builds the run request with objective folded into the axes', () => {
  const b = runBody(['uc-camera-recording'], '', 'Camera Recording', { ...DEFAULT_RUN, runtime_scales: [1.2], objective_scale: 1.0, statistics: ['mean'] })
  expect(b.spec.axes.runtime_scales).toEqual([1.0, 1.2])
  expect(b.spec.axes.statistics).toEqual(['mean', 'max'])
  expect(b.spec.objective).toEqual({ statistic: 'max', runtime_scale: 1.0 })
  expect(b.title).toBeUndefined()
})

it('estimates the case count like the server (SW slices x 2^buffers x DVFS)', () => {
  expect(caseCount(DEFAULT_RUN)).toBe(2 * 3 * 256 * 8)
  expect(caseCount({ ...DEFAULT_RUN, modes: [] })).toBe(2 * 3 * 8)
})

it('computes case deltas and DVFS labels', () => {
  const a = { total_mw: 700, cpu_mw: 300, hw_mw: 130, bw_mw: 270, bw_mbs: 3000 } as ExpCase
  const b = { total_mw: 674, cpu_mw: 300, hw_mw: 127, bw_mw: 247, bw_mbs: 2958 } as ExpCase
  expect(caseDelta(a, b).total).toBe(26)
  expect(levels({ INT: 5, CAM: 4 })).toBe('CAM:L4 INT:L5')
})

it('waterfall steps chain from old to new total', () => {
  const a: Attribution = { old_total_mw: 674, new_total_mw: 867, delta_mw: 193, delta_pct: 28.6, components: { cpu_mw: 0, hw_mw: 0, bw_mw: 193 },
    by_category: { Compression: 193 }, residual_mw: 0, context_changes: [],
    factors: [{ category: 'Compression', item: 'A', delta_mw: 100, detail: '' }, { category: 'Compression', item: 'B', delta_mw: 93, detail: '' }] }
  const s = waterfall(a)
  expect(s[0].start).toBe(674)
  expect(s[s.length - 1].end).toBeCloseTo(867)
})

it('routes the new pages and posts promotion requests', async () => {
  expect(parseHash('#/explore?run=EXP-1').page).toBe('explore')
  expect(parseHash('#/predictions').page).toBe('predictions')
  expect(parseHash('#/reports?report=R').params.report).toBe('R')
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ promoted: [], skipped: [] }) })
  vi.stubGlobal('fetch', fetcher)
  await archApi.promote('EXP-1', ['v1'], 'k', 'why')
  const [url, init] = fetcher.mock.calls[0]
  expect(url).toContain('/arch/predictions/promote')
  expect(JSON.parse(init.body)).toEqual({ run_id: 'EXP-1', variant_ids: ['v1'], case_key: 'k', reason: 'why' })
})
