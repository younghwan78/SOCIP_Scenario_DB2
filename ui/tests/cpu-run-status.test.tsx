// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, it, vi } from 'vitest'
import type { Ctx } from '../src/App'
import { createCpuAnalysis, type CpuAnalysisAdapter } from '../src/lib/cpuAnalysis'
import { cpuApi, type CpuSweep, type CpuSweepRequest } from '../src/lib/cpu'
import type { CpuRebalance, CpuRebalanceRequest } from '../src/lib/rebalance'
import type { GrowthSweep } from '../src/lib/growthSweep'
import { CpuWhatIfPage } from '../src/pages/CpuWhatIf'
import { profileScopes } from '../src/components/CpuScope'
import { ChartTipProvider } from '../src/components/ChartTip'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
if (typeof ResizeObserver === 'undefined') Object.assign(globalThis, { ResizeObserver: class { observe() {} unobserve() {} disconnect() {} } })

const rebalance = JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/cpu-rebalance-e2600.json'), 'utf8')) as CpuRebalance
const sweepResult = (JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/cpu-dsu-sweeps.json'), 'utf8')) as { measured: CpuSweep }).measured
const request = (): CpuRebalanceRequest => ({
  cpu_profile_ref: 'profile', power_params_ref: 'main', fps: 30, default_growth: 1, growth: {}, budgets_ms: {}, threads: {},
  sweep_clusters: {}, knobs: ['pin'], uclamp_max_levels: [], uclamp_min_levels: [], reference: 'measured', power_gating_eff: 0.9,
  cpu_bw_scale: 1, pool: [], locks: {}, co_move: [], timing_coupling: 'stage_slack',
})
const growth = (): GrowthSweep => ({
  profile_ref: 'profile', power_params_ref: 'main', fps: 30, points: [], events: [],
  limits: { opp_step: null, opp_step_best_mw: null, timing_at: null, tolerance: null, binding: null }, elapsed_ms: 1,
})
const settle = async () => { for (let i = 0; i < 4; i++) await Promise.resolve() }

/** Every call waits until the test releases it; `release(i)` resolves the i-th call. */
function gated() {
  const pending: { kind: string; resolve: (v: unknown) => void; reject: (e: Error) => void }[] = []
  const wait = <T,>(kind: string) => new Promise<T>((resolve, reject) => { pending.push({ kind, resolve: resolve as (v: unknown) => void, reject }) })
  const adapter: CpuAnalysisAdapter = {
    sweep: () => wait<CpuSweep>('sweep'), rebalance: () => wait<CpuRebalance>('rebalance'), growth: () => wait<GrowthSweep>('growth'),
  }
  return { adapter, pending }
}

it('reports each stage of a rebalance workflow with its elapsed time and stores the input key with each result', async () => {
  let t = 1000
  const g = gated(), analysis = createCpuAnalysis(g.adapter, [], () => t)
  const done = analysis.execute({ mode: 'rebalance', request: request(), growths: [1, 1.2], comparison: 'other', key: 'K', growthKey: 'G' })
  expect(analysis.getSnapshot().progress).toEqual({ mode: 'rebalance', stages: ['rebalance', 'comparison', 'growth', 'growth-comparison'], index: 0, startedAt: 1000 })
  g.pending[0].resolve(rebalance); await settle()
  expect(analysis.getSnapshot()).toMatchObject({ progress: { index: 1 }, keys: { rebalance: 'K', growth: null } })
  g.pending[1].resolve(rebalance); await settle()
  expect(analysis.getSnapshot().progress?.index).toBe(2)
  g.pending[2].resolve(growth()); await settle()
  expect(analysis.getSnapshot()).toMatchObject({ progress: { index: 3 }, keys: { growth: 'G' } })
  t = 1750
  g.pending[3].resolve(growth()); await done
  expect(analysis.getSnapshot()).toMatchObject({ progress: null, busy: false, done: { mode: 'rebalance', outcome: 'ok', at: 1750, ms: 750 } })
})

it('stop: the page is idle at once, the cut-off responses publish nothing, and the stop is reported', async () => {
  let t = 0
  const g = gated(), analysis = createCpuAnalysis(g.adapter, [], () => t)
  const first = analysis.execute({ mode: 'sweep', request: request() as CpuSweepRequest, key: 'A' })
  g.pending[0].resolve(sweepResult); await first
  const retry = analysis.execute({ mode: 'sweep', request: request() as CpuSweepRequest, key: 'B' })
  t = 300
  analysis.stop()
  expect(analysis.getSnapshot()).toMatchObject({ busy: false, progress: null, result: sweepResult, keys: { sweep: 'A' },
    done: { mode: 'sweep', outcome: 'cancelled', ms: 300 } })
  g.pending[1].resolve({ ...sweepResult, measured_mw: 1 }); await retry
  expect(analysis.getSnapshot()).toMatchObject({ result: sweepResult, keys: { sweep: 'A' }, done: { outcome: 'cancelled' } })
})

it('a standalone growth reports its own progress, but not while a rebalance workflow owns the status', async () => {
  const g = gated(), analysis = createCpuAnalysis(g.adapter)
  const alone = analysis.execute({ mode: 'growth', request: request(), growths: [1], key: 'G1' })
  expect(analysis.getSnapshot().progress).toMatchObject({ mode: 'growth', stages: ['growth'] })
  g.pending[0].resolve(growth()); await alone
  expect(analysis.getSnapshot()).toMatchObject({ progress: null, done: { mode: 'growth', outcome: 'ok' }, keys: { growth: 'G1' } })
  const main = analysis.execute({ mode: 'rebalance', request: request(), growths: [1], key: 'K' })
  const inner = analysis.execute({ mode: 'growth', request: request(), growths: [1], key: 'G2' })
  expect(analysis.getSnapshot().progress).toMatchObject({ mode: 'rebalance', index: 0 })
  g.pending[2].reject(new Error('growth failed')); await inner
  expect(analysis.getSnapshot()).toMatchObject({ progress: { mode: 'rebalance' }, growthError: 'growth failed', keys: { growth: null } })
  g.pending[1].resolve(rebalance); await settle()
  g.pending[3].resolve(growth()); await main
  expect(analysis.getSnapshot()).toMatchObject({ progress: null, done: { mode: 'rebalance', outcome: 'ok' } })
})

it('a failed sweep ends the progress as an error and keeps the previous result and key', async () => {
  const g = gated(), analysis = createCpuAnalysis(g.adapter)
  const ok = analysis.execute({ mode: 'sweep', request: request() as CpuSweepRequest, key: 'A' })
  g.pending[0].resolve(sweepResult); await ok
  const bad = analysis.execute({ mode: 'sweep', request: request() as CpuSweepRequest, key: 'B' })
  g.pending[1].reject(new Error('boom')); await bad
  expect(analysis.getSnapshot()).toMatchObject({ result: sweepResult, keys: { sweep: 'A' }, error: 'boom', done: { outcome: 'error' }, progress: null })
})

it('scenario menu: only variants with a CPU profile, named from the catalog, counted', () => {
  const scopes = profileScopes([
    { id: 'a', project_ref: 'proj', scenario_ref: 'uc-rec', variant_ref: 'v1' },
    { id: 'b', project_ref: 'proj', scenario_ref: 'uc-rec', variant_ref: 'v1' },
    { id: 'c', project_ref: 'proj', scenario_ref: 'uc-rec', variant_ref: 'v2' },
    { id: 'd', project_ref: null, scenario_ref: null, variant_ref: null },
  ], [{ scenario_id: 'uc-rec', scenario_name: 'Recording', project_id: 'proj' } as Ctx['allCatalog'][number]])
  expect(scopes.map((s) => [s.label, s.count])).toEqual([['Recording › v1', 2], ['Recording › v2', 1]])
})

it('page: the scenario menu moves the app selection; edits mark the result stale until the next run', async () => {
  localStorage.setItem('sdb.cpu.mode', JSON.stringify('sweep'))
  const inputs = vi.spyOn(cpuApi, 'inputs').mockResolvedValue({
    profiles: [
      { id: 'p1', project_ref: 'proj', scenario_ref: 'uc-rec', variant_ref: 'v1', tasks: [{ task: 'ui', cluster: 'BIG' }] },
      { id: 'p2', project_ref: 'proj', scenario_ref: 'uc-rec', variant_ref: 'v2', tasks: [{ task: 'ui', cluster: 'BIG' }] },
    ],
    topologies: [{ id: 'target', version: 1, soc_ref: 'soc-x', clusters: ['BIG'] }],
  })
  const calls: CpuSweepRequest[] = []
  const sweep = vi.spyOn(cpuApi, 'sweep').mockImplementation(async (req) => { calls.push(req); return sweepResult })
  const navigate = vi.fn()
  const ctx = { project: 'proj', scenario: 'uc-rec', variant: 'v2', allCatalog: [], projects: [], navigate } as unknown as Ctx
  const host = document.createElement('div'), root = createRoot(host)
  const status = () => host.querySelector('[aria-label="계산 상태"]')!.textContent ?? ''
  try {
    await act(async () => root.render(<ChartTipProvider><CpuWhatIfPage ctx={ctx} /></ChartTipProvider>))
    expect(calls[0].cpu_profile_ref).toBe('p2')                     // the selected variant's profile
    const scope = host.querySelector<HTMLSelectElement>('select[aria-label="scenario · variant"]')!
    expect([...scope.options].map((o) => o.textContent)).toEqual(['uc-rec › v1 (1)', 'uc-rec › v2 (1)'])
    expect(status()).toContain('마지막 계산')
    expect(status()).toContain('결과 = 현재 조건')
    await act(async () => { scope.value = scope.options[0].value; scope.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(navigate).toHaveBeenCalledWith('cpu', { scenario: 'uc-rec', variant: 'v1' })
    const fps = [...host.querySelectorAll('label')].find((l) => l.textContent?.startsWith('fps'))!.querySelector('input')!
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(fps, '60')
      fps.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(calls).toHaveLength(1)                                     // edits never run by themselves
    expect(status()).toContain('조건 변경됨')
    await act(async () => [...host.querySelectorAll('button')].find((b) => b.textContent === '변경 반영 계산')!.click())
    expect(calls[1].fps).toBe(60)
    expect(status()).toContain('결과 = 현재 조건')
    // the shown result is for 60 fps now, so going back to 30 is a change again
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(fps, '30')
      fps.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(status()).toContain('조건 변경됨')
  } finally { act(() => root.unmount()); inputs.mockRestore(); sweep.mockRestore(); localStorage.clear() }
})

it('a failed comparison or growth stage after the main result ends the workflow as partial, naming the stages', async () => {
  const g = gated(), analysis = createCpuAnalysis(g.adapter)
  const done = analysis.execute({ mode: 'rebalance', request: request(), growths: [1], comparison: 'other' })
  g.pending[0].resolve(rebalance); await settle()
  g.pending[1].reject(new Error('comparison failed')); await settle()
  g.pending[2].resolve(growth()); await settle()
  g.pending[3].reject(new Error('comparison growth failed')); await done
  expect(analysis.getSnapshot()).toMatchObject({ rebalance, error: null, comparisonError: 'comparison failed',
    done: { outcome: 'partial', failed: ['comparison', 'growth-comparison'] } })
})

it('a variant picked on the CPU page opens in the CPU page (as on Timing / Behavior)', async () => {
  const { pickerTarget } = await import('../src/App')
  expect(pickerTarget('cpu')).toBe('cpu')
  expect(pickerTarget('timing')).toBe('timing')
  expect(pickerTarget('explore')).toBe('pipeline')
})
