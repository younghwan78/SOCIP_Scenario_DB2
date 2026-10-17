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
import { powerParts } from '../src/components/RebalanceView'
import { ChartTipProvider } from '../src/components/ChartTip'
import { sweepApi } from '../src/lib/growthSweep'

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

it('rebalance measured DSU experiments retain the exported residency', () => {
  const raw = { ...E2600, dsu_measured: { '1500': 1 } }
  const fixed = applyDsuRebalance(raw, { mode: 'fixed', fixed_mhz: 1500 })
  const measured = applyDsuRebalance(raw, { mode: 'measured' })
  expect(measured.reference.total_mw).toBeCloseTo(fixed.reference.total_mw, 6)
  expect(measured.reference.mhz.dsu).toBe(1500)
  expect(measured.cases.map((c) => c.total_mw)).toEqual(fixed.cases.map((c) => c.total_mw))
  expect(measured.opp_states.map((s) => s.min_mw)).toEqual(fixed.opp_states.map((s) => s.min_mw))
})

it('rebalance mode: setup, run with locks / co-move, curve and top splits', async () => {
  localStorage.setItem('sdb.cpu.mode', JSON.stringify('rebalance'))
  localStorage.setItem('sdb.cpu.inputs.open', 'true')   // inputs are folded by default once a result exists
  const growth = vi.spyOn(sweepApi, 'run').mockRejectedValue(new Error('growth sweep not under test'))
  const tasks = E2600.units.flatMap((u) => u.tasks.map((t) => ({ task: t, cluster: u.home })))
  const inputs = vi.spyOn(cpuApi, 'inputs').mockResolvedValue({
    profiles: [{ id: 'p1', scenario_ref: null, variant_ref: null, project_ref: null, tasks }],
    topologies: [{ id: 'pmp-e2600', version: 1, soc_ref: 'soc-exynos2600', clusters: ['MID_LF0', 'MID_LF1', 'MID_HF', 'BIG'] }],
  })
  const calls: CpuRebalanceRequest[] = []
  const run = vi.spyOn(rebalanceApi, 'run').mockImplementation(async (req) => { calls.push(req); return { ...E2600, dsu_measured: { '1500': 1 } } })
  const sweep = vi.spyOn(cpuApi, 'sweep').mockRejectedValue(new Error('sweep must not run in rebalance mode'))
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<ChartTipProvider><CpuWhatIfPage ctx={{} as Ctx} /></ChartTipProvider>))
    expect(calls).toHaveLength(1)
    expect(calls[0].pool).toEqual([])                       // first run: server default pool
    expect(host.querySelector('select[aria-label="DSU 실험 규칙"] option[value="measured"]')).not.toBeNull()
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
  } finally { act(() => root.unmount()); inputs.mockRestore(); run.mockRestore(); sweep.mockRestore(); growth.mockRestore(); localStorage.clear() }
})

it('과제 비교: second rebalance on the other topology, measured SoC as base, only exclude locks kept', async () => {
  localStorage.setItem('sdb.cpu.mode', JSON.stringify('rebalance'))
  localStorage.setItem('sdb.cpu.inputs.open', 'true')   // inputs are folded by default once a result exists
  const growth = vi.spyOn(sweepApi, 'run').mockRejectedValue(new Error('growth sweep not under test'))
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
  } finally { act(() => root.unmount()); inputs.mockRestore(); run.mockRestore(); growth.mockRestore(); localStorage.clear() }
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

it('power breakdown order: DSU → pool clusters (topology order) → outside-pool clusters by name', () => {
  expect(powerParts(E2600).map((p) => p.label)).toEqual(['DSU', 'MID_LF0', 'MID_LF1', 'MID_HF', 'BIG (pool 밖)'])
  expect(powerParts({ ...E2600, pool: ['MID_HF', 'MID_LF0'] }).map((p) => p.label)).toEqual(['DSU', 'MID_LF0', 'MID_HF', 'MID_LF1 + BIG (pool 밖)'])
})

it('result first: inputs fold after the first result and the growth sweep reuses the rebalance request', async () => {
  localStorage.setItem('sdb.cpu.mode', JSON.stringify('rebalance'))
  const tasks = E2600.units.flatMap((u) => u.tasks.map((t) => ({ task: t, cluster: u.home })))
  const inputs = vi.spyOn(cpuApi, 'inputs').mockResolvedValue({
    profiles: [{ id: 'p1', scenario_ref: null, variant_ref: null, project_ref: null, tasks, origin: 'synthetic' }],
    topologies: [{ id: 'pmp-e2600', version: 1, soc_ref: 'soc-exynos2600', clusters: ['MID_LF0', 'MID_LF1', 'MID_HF', 'BIG'] }],
  })
  const run = vi.spyOn(rebalanceApi, 'run').mockResolvedValue(E2600)
  const pts = [1, 1.1].map((g) => ({ growth: g, reference: { total_mw: 237 * g, feasible: true, mhz: { MID_LF0: 1600, dsu: 645 }, mw: {}, moved: [] },
    best: { total_mw: 232 * g, feasible: true, mhz: { MID_LF0: 1600, dsu: 645 }, mw: {}, moved: ['a'] },
    strategies: [{ kind: 'spread' as const, clusters: ['MID_LF0', 'MID_LF1'], total_mw: 232 * g, feasible: true, mhz: {} }],
    winner: 'spread', big_gain_mw: null, cpu_bw_mbs: 870, feasible_count: 1, stages: [] }))
  const growth = vi.spyOn(sweepApi, 'run').mockResolvedValue({ profile_ref: 'p1', power_params_ref: 'pmp-e2600', fps: 30, points: pts, events: [],
    limits: { opp_step: null, opp_step_best_mw: null, timing_at: null, tolerance: null, binding: null }, elapsed_ms: 10 })
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<ChartTipProvider><CpuWhatIfPage ctx={{} as Ctx} /></ChartTipProvider>))
    expect(run).toHaveBeenCalledTimes(1)
    expect(growth).toHaveBeenCalledTimes(1)
    const req = growth.mock.calls[0][0]
    expect(req.growths).toEqual([1, 1.1, 1.2, 1.3, 1.4, 1.5])
    expect(req.cpu_profile_ref).toBe('p1')
    expect(host.querySelector('[aria-label="CPU what-if 결론"]')?.textContent).toContain('합성 profile')
    const labelled = (sel: string, label: string) => [...host.querySelectorAll(sel)].some((x) => x.getAttribute('aria-label') === label)
    expect(labelled('svg', 'SW 증가 배율에 따른 CPU + DSU 전력')).toBe(true)
    expect(host.textContent).toContain('조건 편집')
    expect(labelled('section', '① 기준')).toBe(false)        // folded
    const open = [...host.querySelectorAll('button')].find((b) => b.textContent?.includes('조건 편집'))!
    await act(async () => open.click())
    expect(labelled('section', '① 기준')).toBe(true)
  } finally { act(() => root.unmount()); inputs.mockRestore(); run.mockRestore(); growth.mockRestore(); localStorage.clear() }
})

it('discards a pending growth sweep when the measurement profile changes', async () => {
  localStorage.setItem('sdb.cpu.mode', JSON.stringify('rebalance'))
  const tasks = E2600.units.flatMap((u) => u.tasks.map((t) => ({ task: t, cluster: u.home })))
  const inputs = vi.spyOn(cpuApi, 'inputs').mockResolvedValue({
    profiles: ['p1', 'p2'].map((id) => ({ id, scenario_ref: null, variant_ref: null, project_ref: null, tasks })),
    topologies: [{ id: 'pmp-e2600', version: 1, soc_ref: 'soc-exynos2600', clusters: ['MID_LF0', 'MID_LF1', 'MID_HF', 'BIG'] }],
  })
  const run = vi.spyOn(rebalanceApi, 'run').mockImplementation((r) => r.cpu_profile_ref === 'p1'
    ? Promise.resolve(E2600) : new Promise(() => {}))
  type Sweep = Awaited<ReturnType<typeof sweepApi.run>>
  let finish!: (s: Sweep) => void
  const growth = vi.spyOn(sweepApi, 'run').mockImplementation(() => new Promise((resolve) => { finish = resolve }))
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<ChartTipProvider><CpuWhatIfPage ctx={{} as Ctx} /></ChartTipProvider>))
    expect(growth).toHaveBeenCalledTimes(1)
    await act(async () => [...host.querySelectorAll('button')].find((b) => b.textContent?.includes('조건 편집'))!.click())
    const profile = [...host.querySelectorAll('label')].find((l) => l.textContent?.startsWith('측정 profile'))!.querySelector('select')!
    await act(async () => { profile.value = 'p2'; profile.dispatchEvent(new Event('change', { bubbles: true })) })
    const split = { total_mw: 237, feasible: true, mhz: { MID_LF0: 1600, dsu: 645 }, mw: {}, moved: [] }
    await act(async () => finish({ profile_ref: 'p1', power_params_ref: 'pmp-e2600', fps: 30,
      points: [1, 1.1].map((g) => ({ growth: g, reference: split, best: split, strategies: [], winner: null,
        big_gain_mw: null, cpu_bw_mbs: 870, feasible_count: 1, stages: [] })), events: [],
      limits: { opp_step: null, opp_step_best_mw: null, timing_at: null, tolerance: null, binding: null }, elapsed_ms: 10 }))
    expect(host.querySelector('[aria-label="CPU what-if 결론"]')).toBeNull()
  } finally { act(() => root.unmount()); inputs.mockRestore(); run.mockRestore(); growth.mockRestore(); localStorage.clear() }
})
