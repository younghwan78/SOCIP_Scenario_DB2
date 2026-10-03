// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Ctx } from '../src/App'
import { cpuApi } from '../src/lib/cpu'
import { applyDsuRebalance, defaultPool, rebalanceApi, type CpuRebalance, type CpuRebalanceRequest } from '../src/lib/rebalance'
import { CpuWhatIfPage } from '../src/pages/CpuWhatIf'
import { ChartTipProvider } from '../src/components/ChartTip'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
if (typeof ResizeObserver === 'undefined') Object.assign(globalThis, { ResizeObserver: class { observe() {} unobserve() {} disconnect() {} } })
const load = (k: string) => JSON.parse(readFileSync(join(process.cwd(), `tests/fixtures/cpu-rebalance-${k}.json`), 'utf-8')) as CpuRebalance
const E2600 = load('e2600'), E2800 = load('e2800')

it('fixtures: next-gen MID_HF0/HF1 pool is symmetric, E2600 splits over MID_LF0/LF1/HF', () => {
  expect(E2600.pool).toEqual(['MID_LF0', 'MID_LF1', 'MID_HF'])
  expect(E2800.pool).toEqual(['MID_HF0', 'MID_HF1'])
  expect(E2800.symmetric).toEqual([['MID_HF0', 'MID_HF1']])
  for (const r of [E2600, E2800]) {
    expect(r.best!.total_mw).toBeLessThan(r.reference.total_mw)
    for (const c of r.cases) expect(Math.abs(c.model_err_mw ?? 0)).toBeLessThan(1e-3)
  }
  expect(defaultPool(['MID_HF0', 'MID_HF1', 'BIG_LF', 'BIG'])).toEqual(['MID_HF0', 'MID_HF1'])
})

it('DSU rule change re-evaluates the returned splits client-side', () => {
  const fixed = applyDsuRebalance(E2600, { mode: 'fixed', fixed_mhz: 1500 })
  expect(fixed.reference.mhz.dsu).toBe(1500)
  for (const c of fixed.cases) expect(c.mhz.dsu).toBe(1500)
  // with the DSU pinned at the top the saving shrinks (the vote no longer drops with the busy cluster)
  expect(fixed.reference.total_mw - fixed.best!.total_mw).toBeLessThan(E2600.reference.total_mw - E2600.best!.total_mw)
  const same = applyDsuRebalance(E2600, { mode: 'vote', vote: E2600.dsu_model!.vote })
  expect(same.best!.total_mw).toBeCloseTo(E2600.best!.total_mw, 2)
  expect(same.curve.map((p) => p.total_mw.toFixed(2))).toEqual(E2600.curve.map((p) => p.total_mw.toFixed(2)))
})

it('rebalance mode: setup, run with locks / co-move, curve and top splits', async () => {
  localStorage.setItem('sdb.cpu.mode', JSON.stringify('rebalance'))
  const tasks = E2600.units.flatMap((u) => u.tasks.map((t) => ({ task: t, cluster: u.home })))
  const inputs = vi.spyOn(cpuApi, 'inputs').mockResolvedValue({
    profiles: [{ id: 'p1', scenario_ref: null, variant_ref: null, project_ref: null, tasks }],
    topologies: [{ id: 'pmp-e2600', version: 1, soc_ref: 'soc-exynos2600', clusters: ['MID_LF0', 'MID_LF1', 'MID_HF', 'BIG'] }],
  })
  const calls: CpuRebalanceRequest[] = []
  const run = vi.spyOn(rebalanceApi, 'run').mockImplementation(async (req) => { calls.push(req); return E2600 })
  const sweep = vi.spyOn(cpuApi, 'sweep').mockRejectedValue(new Error('sweep must not run in rebalance mode'))
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<ChartTipProvider><CpuWhatIfPage ctx={{} as Ctx} /></ChartTipProvider>))
    expect(calls).toHaveLength(1)
    expect(calls[0].pool).toEqual([])                       // first run: server default pool
    expect(sweep).not.toHaveBeenCalled()
    expect(host.querySelector('svg[aria-label="이동 곡선"]')).not.toBeNull()
    expect(host.textContent).toContain('최저 분배')
    expect(host.querySelectorAll(`section[aria-label="최저 분배 상위 ${E2600.cases.length}"] tbody tr`)).toHaveLength(E2600.cases.length)
    // pin one task, group two, drop MID_HF from the pool, rerun
    const st = host.querySelector<HTMLSelectElement>('select[aria-label="eis_vdis 상태"]')!
    await act(async () => { st.value = 'pin:MID_LF1'; st.dispatchEvent(new Event('change', { bubbles: true })) })
    for (const t of ['cam_hal_request', 'cam_hal_result']) {
      const g = host.querySelector<HTMLSelectElement>(`select[aria-label="${t} 함께 이동"]`)!
      await act(async () => { g.value = 'G1'; g.dispatchEvent(new Event('change', { bubbles: true })) })
    }
    const hf = [...host.querySelectorAll('label')].find((l) => l.textContent === 'MID_HF')!.querySelector('input')!
    await act(async () => hf.click())
    const btn = [...host.querySelectorAll('button')].find((b) => b.textContent === '다시 계산')!
    await act(async () => btn.click())
    const last = calls.at(-1)!
    expect(last.locks).toEqual({ eis_vdis: 'MID_LF1' })
    expect(last.co_move).toEqual([['cam_hal_request', 'cam_hal_result']])
    expect(last.pool).toEqual(['MID_LF0', 'MID_LF1'])
    expect(last.top).toBe(20)
  } finally { act(() => root.unmount()); inputs.mockRestore(); run.mockRestore(); sweep.mockRestore(); localStorage.clear() }
})
