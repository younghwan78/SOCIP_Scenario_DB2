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


/** Click one option of a segmented control (radiogroup) by aria-label + value. */
async function pick(host: HTMLElement, label: string, value: string) {
  const b = host.querySelector<HTMLButtonElement>(`[role="radiogroup"][aria-label="${label}"] button[data-value="${value}"]`)!
  expect(b).not.toBeNull()
  await act(async () => b.click())
  expect(b.getAttribute('aria-checked')).toBe('true')
}

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
    await pick(host, 'eis_vdis 상태', 'pin:MID_LF1')
    expect(host.querySelector('[aria-label="eis_vdis 함께 이동"] button')!.hasAttribute('disabled')).toBe(true)   // pinned → no group
    for (const t of ['cam_hal_request', 'cam_hal_result']) await pick(host, `${t} 함께 이동`, 'camera-daemon')
    expect(host.querySelector('[aria-label="cgroup 구성"]')!.textContent).toContain('camera-daemon 2 task')
    expect(JSON.parse(localStorage.getItem('sdb.cpu.rb.cgroup')!)).toEqual({ cam_hal_request: 'camera-daemon', cam_hal_result: 'camera-daemon' })   // kept by task name
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

it('과제 비교: second rebalance on the other topology, measured SoC as base, only exclude locks kept', async () => {
  localStorage.setItem('sdb.cpu.mode', JSON.stringify('rebalance'))
  const tasks = E2600.units.flatMap((u) => u.tasks.map((t) => ({ task: t, cluster: u.home })))
  const inputs = vi.spyOn(cpuApi, 'inputs').mockResolvedValue({
    profiles: [{ id: 'p1', scenario_ref: null, variant_ref: null, project_ref: null, tasks }],
    topologies: [{ id: 'pmp-e2600', version: 1, soc_ref: 'soc-exynos2600', clusters: ['MID_LF0', 'MID_LF1', 'MID_HF', 'BIG'] },
      { id: 'pmp-e2800', version: 1, soc_ref: 'soc-exynos2800', clusters: ['MID_HF0', 'MID_HF1', 'BIG_LF', 'BIG'] }],
  })
  const calls: CpuRebalanceRequest[] = []
  const run = vi.spyOn(rebalanceApi, 'run').mockImplementation(async (req) => { calls.push(req); return req.power_params_ref === 'pmp-e2800' ? E2800 : E2600 })
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<ChartTipProvider><CpuWhatIfPage ctx={{} as Ctx} /></ChartTipProvider>))
    const cmp = host.querySelector<HTMLSelectElement>('select[aria-label="비교할 SoC"]')!
    await act(async () => { cmp.value = 'pmp-e2800'; cmp.dispatchEvent(new Event('change', { bubbles: true })) })
    await pick(host, 'isp_ctrl 상태', 'exclude')
    await pick(host, 'eis_vdis 상태', 'pin:MID_LF1')
    await act(async () => [...host.querySelectorAll('button')].find((b) => b.textContent === '다시 계산')!.click())
    const [main, other] = calls.slice(-2)
    expect(main.power_params_ref).toBe('pmp-e2600')
    expect(other.power_params_ref).toBe('pmp-e2800')
    expect(other.base_power_params_ref).toBe('pmp-e2600')
    expect(other.locks).toEqual({ isp_ctrl: 'exclude' })
    expect(other.pool).toEqual([])
    const table = host.querySelector('table[aria-label="과제 비교"]')!
    expect(table.textContent).toContain('soc-exynos2800')
    expect(table.textContent).toContain(`${E2800.best!.total_mw.toFixed(1)} mW`)
  } finally { act(() => root.unmount()); inputs.mockRestore(); run.mockRestore(); localStorage.clear() }
})

it('가정 민감도: DSU corners instantly, other assumptions rerun sequentially, flags a changed split', async () => {
  const { AssumptionSensitivity } = await import('../src/components/RebalanceView')
  const patches: Record<string, unknown>[] = []
  const shifted: CpuRebalance = { ...E2600, best: { ...E2600.best!, total_mw: E2600.best!.total_mw + 30, moved: ['eis_vdis'], assign: { ...E2600.best!.assign, eis_vdis: 'MID_HF' } } }
  const runVariant = async (patch: Record<string, unknown>) => { patches.push(patch); return patch.default_growth === 1.2 ? shifted : E2600 }
  const host = document.createElement('div'), root = createRoot(host)
  await act(async () => root.render(<ChartTipProvider><AssumptionSensitivity base={E2600} runVariant={runVariant} dsu={null} /></ChartTipProvider>))
  await act(async () => [...host.querySelectorAll('button')].find((b) => b.textContent === '민감도 계산')!.click())
  expect(patches).toEqual([{ default_growth: 0.9 }, { default_growth: 1.2 }, { freq_margin: 1.15 }, { freq_margin: 1.35 }, { power_gating_eff: 0.8 }, { power_gating_eff: 0.95 }])
  const rows = [...host.querySelectorAll('table[aria-label="가정 민감도"] tbody tr')].map((tr) => tr.textContent ?? '')
  expect(rows).toHaveLength(4)
  expect(rows.find((r) => r.startsWith('SW 부하 증가'))).toContain('바뀜 1/2')
  expect(rows.find((r) => r.startsWith('DSU vote 표'))).toBeTruthy()
  act(() => root.unmount())
})
