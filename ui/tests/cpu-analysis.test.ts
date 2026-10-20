import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, it } from 'vitest'
import { createCpuAnalysis, type CpuAnalysisAdapter, type CpuAnalysisState, type GrowthRequest } from '../src/lib/cpuAnalysis'
import type { CpuSweep, CpuSweepRequest } from '../src/lib/cpu'
import type { CpuRebalance, CpuRebalanceRequest } from '../src/lib/rebalance'
import type { GrowthSweep } from '../src/lib/growthSweep'

const rebalance = JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/cpu-rebalance-e2600.json'), 'utf8')) as CpuRebalance
const sweep = (JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/cpu-dsu-sweeps.json'), 'utf8')) as { measured: CpuSweep }).measured
const request = (): CpuRebalanceRequest => ({
  cpu_profile_ref: 'profile', power_params_ref: 'main', fps: 30, default_growth: 1,
  growth: { camera: 1.1 }, budgets_ms: {}, threads: {}, sweep_clusters: {}, knobs: ['pin'],
  uclamp_max_levels: [], uclamp_min_levels: [], reference: 'measured', power_gating_eff: 0.9,
  cpu_bw_scale: 1, pool: ['MID_LF0', 'MID_LF1'], locks: { camera: 'MID_LF0', idle: 'exclude' },
  co_move: [['a', 'b']], timing_coupling: 'stage_slack',
})
const growth = (target = 'main'): GrowthSweep => ({
  profile_ref: 'profile', power_params_ref: target, fps: 30, points: [], events: [],
  limits: { opp_step: null, opp_step_best_mw: null, timing_at: null, tolerance: null, binding: null }, elapsed_ms: 1,
})
const settle = async () => { await Promise.resolve(); await Promise.resolve() }
const deferred = <T,>() => {
  let resolve!: (result: T) => void, reject!: (reason: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve: async (result: T) => { resolve(result); await settle() }, reject: async (reason: string) => { reject(new Error(reason)); await settle() } }
}

/** A real adapter: tests control every response without reaching into the analysis implementation. */
function controlled() {
  const calls: string[] = []
  const rebalances: { request: CpuRebalanceRequest; response: ReturnType<typeof deferred<CpuRebalance>> }[] = []
  const growths: { request: GrowthRequest; response: ReturnType<typeof deferred<GrowthSweep>> }[] = []
  const sweeps: { request: CpuSweepRequest; response: ReturnType<typeof deferred<CpuSweep>> }[] = []
  const adapter: CpuAnalysisAdapter = {
    rebalance: (request) => {
      calls.push(`rebalance:${request.power_params_ref}`)
      const response = deferred<CpuRebalance>(); rebalances.push({ request, response }); return response.promise
    },
    growth: (request) => {
      calls.push(`growth:${request.power_params_ref}`)
      const response = deferred<GrowthSweep>(); growths.push({ request, response }); return response.promise
    },
    sweep: (request) => {
      calls.push(`sweep:${request.power_params_ref}`)
      const response = deferred<CpuSweep>(); sweeps.push({ request, response }); return response.promise
    },
  }
  return { adapter, calls, rebalances, growths, sweeps }
}

it('keeps the last successful sweep visible through a pending and failed retry', async () => {
  const c = controlled(), analysis = createCpuAnalysis(c.adapter)
  const initial = analysis.execute({ mode: 'sweep', request: request() })
  await c.sweeps[0].response.resolve(sweep)
  await initial
  const retry = analysis.execute({ mode: 'sweep', request: { ...request(), default_growth: 1.2 } })
  expect(analysis.getSnapshot()).toMatchObject({ result: sweep, busy: true, error: null })
  await c.sweeps[1].response.reject('sweep unavailable')
  await retry
  expect(analysis.getSnapshot()).toMatchObject({ result: sweep, busy: false, error: 'sweep unavailable' })
  const replacement = analysis.execute({ mode: 'sweep', request: request() })
  const newer = { ...sweep, measured_mw: 123 }
  await c.sweeps[2].response.resolve(newer)
  await replacement
  expect(analysis.getSnapshot()).toMatchObject({ result: newer, error: null })
})

it('clears the sweep on a selection transition while optionally retaining the rebalance display', async () => {
  const c = controlled(), analysis = createCpuAnalysis(c.adapter)
  const main = analysis.execute({ mode: 'rebalance', request: request(), growths: [1, 1.5] })
  await c.rebalances[0].response.resolve(rebalance)
  await c.growths[0].response.resolve(growth())
  await main
  const initial = analysis.execute({ mode: 'sweep', request: request() })
  await c.sweeps[0].response.resolve(sweep)
  await initial
  const pending = analysis.execute({ mode: 'sweep', request: request() })
  analysis.reset({ keepRebalance: true })
  expect(analysis.getSnapshot()).toMatchObject({
    result: null, rebalance, growth: { result: growth() }, busy: false, snapshotRequest: null,
  })
  await c.sweeps[1].response.resolve(sweep)
  await pending
  expect(analysis.getSnapshot().result).toBeNull()
  analysis.reset()
  expect(analysis.getSnapshot()).toMatchObject({ result: null, rebalance: null, growth: null })
  expect(analysis.getSnapshot().runs).toHaveLength(1)
})

it('runs main, comparison and both growths sequentially with a captured request and review ownership', async () => {
  const c = controlled(), analysis = createCpuAnalysis(c.adapter)
  const observed: CpuAnalysisState[] = []
  const unsubscribe = analysis.subscribe(() => observed.push(analysis.getSnapshot()))
  const input = request(), grid = [1, 1.5]
  const done = analysis.execute({ mode: 'rebalance', request: input, growths: grid, comparison: 'comparison' })
  input.growth.camera = 2; input.locks.idle = 'BIG'; grid[1] = 2
  expect(c.calls).toEqual(['rebalance:main'])
  await c.rebalances[0].response.resolve(rebalance)
  expect(c.calls).toEqual(['rebalance:main', 'rebalance:comparison'])
  expect(c.rebalances[1].request).toMatchObject({
    power_params_ref: 'comparison', base_power_params_ref: 'main', pool: [], locks: { idle: 'exclude' }, growth: { camera: 1.1 },
  })
  expect(analysis.getSnapshot().snapshotRequest).toBeNull()
  await c.rebalances[1].response.resolve(rebalance)
  expect(c.calls).toEqual(['rebalance:main', 'rebalance:comparison', 'growth:main'])
  expect(c.growths[0].request.growths).toEqual([1, 1.5])
  await c.growths[0].response.resolve(growth())
  expect(c.calls).toEqual(['rebalance:main', 'rebalance:comparison', 'growth:main', 'growth:comparison'])
  expect(analysis.getSnapshot().snapshotRequest).toBeNull()
  await c.growths[1].response.resolve(growth('comparison'))
  await done
  const state = analysis.getSnapshot()
  expect(state.snapshotRequest).toEqual(c.growths[0].request)
  expect(state.growth?.request).toBe(state.snapshotRequest)
  expect(state.comparisonGrowth?.power_params_ref).toBe('comparison')
  expect(state.runs).toHaveLength(1)
  expect(JSON.parse(state.runs[0].context).growth).toEqual({ camera: 1.1 })
  expect(state.runs[0]).toMatchObject({ n: 1, profile: 'profile', target: 'main', cmp: 'comparison' })
  expect(observed.some((s) => s.rebalance && s.busy && !s.growth)).toBe(true)
  expect(state).toMatchObject({ busy: false, growthBusy: false, error: null })
  unsubscribe()
  analysis.cancel()
  expect(analysis.getSnapshot().growth?.result).toEqual(growth())
  expect(analysis.getSnapshot().snapshotRequest).toBeNull()
})

it.each(['main', 'comparison', 'growth', 'comparisonGrowth'] as const)(
  'discards a replaced profile at the %s stage without continuing the old workflow',
  async (stage) => {
    const c = controlled(), analysis = createCpuAnalysis(c.adapter)
    const old = analysis.execute({ mode: 'rebalance', request: request(), growths: [1, 1.5], comparison: 'comparison' })
    if (stage !== 'main') await c.rebalances[0].response.resolve(rebalance)
    if (stage === 'growth' || stage === 'comparisonGrowth') await c.rebalances[1].response.resolve(rebalance)
    if (stage === 'comparisonGrowth') await c.growths[0].response.resolve(growth())
    analysis.reset()
    const current = analysis.execute({ mode: 'sweep', request: { ...request(), cpu_profile_ref: 'new-profile' } })
    const count = c.calls.length
    if (stage === 'main') await c.rebalances[0].response.resolve(rebalance)
    if (stage === 'comparison') await c.rebalances[1].response.resolve(rebalance)
    if (stage === 'growth') await c.growths[0].response.resolve(growth())
    if (stage === 'comparisonGrowth') await c.growths[1].response.resolve(growth('comparison'))
    await old
    expect(c.calls).toHaveLength(count)
    expect(analysis.getSnapshot()).toMatchObject({ rebalance: null, growth: null, snapshotRequest: null, busy: true })
    await c.sweeps[0].response.reject('current response')
    await current
    expect(analysis.getSnapshot()).toMatchObject({ error: 'current response', busy: false })
  },
)

it('keeps main results and runs growth after comparison failures', async () => {
  const c = controlled(), analysis = createCpuAnalysis(c.adapter)
  const done = analysis.execute({ mode: 'rebalance', request: { ...request(), base_power_params_ref: 'measured' }, growths: [1, 1.5], comparison: 'comparison' })
  await c.rebalances[0].response.resolve(rebalance)
  expect(c.rebalances[1].request.base_power_params_ref).toBe('measured')
  await c.rebalances[1].response.reject('comparison unavailable')
  await c.growths[0].response.resolve(growth())
  await c.growths[1].response.reject('comparison growth unavailable')
  await done
  expect(analysis.getSnapshot()).toMatchObject({
    rebalance, comparison: null, error: null, comparisonError: 'comparison unavailable',
    comparisonGrowthError: 'comparison growth unavailable', busy: false, growthBusy: false,
  })
  expect(analysis.getSnapshot().snapshotRequest).toEqual(c.growths[0].request)
  expect(analysis.getSnapshot().runs[0].cmp).toBeNull()
})

it('retries failed growth independently without duplicating history or exposing the previous snapshot', async () => {
  const c = controlled(), analysis = createCpuAnalysis(c.adapter)
  const done = analysis.execute({ mode: 'rebalance', request: request(), growths: [1, 1.5] })
  await c.rebalances[0].response.resolve(rebalance)
  await c.growths[0].response.reject('growth failed')
  await done
  expect(analysis.getSnapshot()).toMatchObject({ rebalance, growth: null, growthError: 'growth failed', snapshotRequest: null })
  const retry = analysis.execute({ mode: 'growth', request: request(), growths: [1, 2] })
  expect(analysis.getSnapshot()).toMatchObject({ busy: false, growthBusy: true, snapshotRequest: null })
  await c.growths[1].response.resolve(growth())
  await retry
  expect(c.rebalances).toHaveLength(1)
  expect(analysis.getSnapshot().runs).toHaveLength(1)
  expect(analysis.getSnapshot().snapshotRequest?.growths).toEqual([1, 2])
  analysis.clearHistory()
  expect(analysis.getSnapshot().runs).toEqual([])
  expect(analysis.getSnapshot().snapshotRequest?.growths).toEqual([1, 2])
})

it('a standalone growth replaces a pending main calculation and owns the only recordable result', async () => {
  const c = controlled(), analysis = createCpuAnalysis(c.adapter)
  const old = analysis.execute({ mode: 'rebalance', request: request(), growths: [1, 1.5], comparison: 'comparison' })
  const current = analysis.execute({ mode: 'growth', request: request(), growths: [1, 2] })
  await c.rebalances[0].response.resolve(rebalance)
  await old
  expect(c.calls).toEqual(['rebalance:main', 'growth:main'])
  expect(analysis.getSnapshot()).toMatchObject({ busy: false, growthBusy: true, rebalance: null, runs: [], snapshotRequest: null })
  await c.growths[0].response.resolve(growth())
  await current
  expect(analysis.getSnapshot().snapshotRequest?.growths).toEqual([1, 2])
})
