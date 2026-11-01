// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, it, vi } from 'vitest'
import type { Ctx } from '../src/App'
import { cpuApi, type CpuSweep, type CpuSweepRequest } from '../src/lib/cpu'
import { rebalanceApi, slackVerdict, type CpuRebalance, type CpuRebalanceRequest, type TimingCoupling } from '../src/lib/rebalance'
import { sweepApi } from '../src/lib/growthSweep'
import { CpuWhatIfPage } from '../src/pages/CpuWhatIf'
import { chainOrder, RtChainCard } from '../src/components/RtChain'
import { ChartTipProvider } from '../src/components/ChartTip'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
if (typeof ResizeObserver === 'undefined') Object.assign(globalThis, { ResizeObserver: class { observe() {} unobserve() {} disconnect() {} } })

const sweepResult = (JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/cpu-dsu-sweeps.json'), 'utf8')) as { measured: CpuSweep }).measured
const E2600 = JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/cpu-rebalance-e2600.json'), 'utf8')) as CpuRebalance

const coupling = (over: Partial<TimingCoupling['stages'][number]> = {}): TimingCoupling => ({
  mode: 'stage_slack', enforced: true, scenario_id: 'uc-rec', variant_id: 'uhd30', statistic: 'max', runtime_scale: 1, period_ms: 33.3,
  stretch: {}, matched_tasks: [], unmatched_tasks: [], impact: { reference: [], best: null },
  stages: [{ stage: 'nrt', sw_ms: 11.1, hw_ms: 18.5, overhead_ms: 0, room_ms: 14.8, slack_ms: 3.7, stretch: 1.34, tasks: [],
    order: [['post_crta', 'post_irta'], ['post_crta', 'pre_me_rta'], ['pre_me_rta', 'post_irta']], serial: true, ...over }],
})

it('RT chain: members in pipeline order with their class; a chain longer than a frame is not used for the wait', async () => {
  expect(chainOrder([['b', 'c'], ['a', 'b'], ['a', 'c']])).toEqual({ tasks: ['a', 'b', 'c'], total: true })
  expect(chainOrder([['a', 'b'], ['a', 'c']]).total).toBe(false)          // b and c are parallel branches
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<RtChainCard coupling={coupling()} rtPlacement="cpupri"
      sched={{ post_crta: { sched_class: 'fifo', rt_priority: 1 }, pre_me_rta: { sched_class: 'fifo', rt_priority: 1 } }} />))
    expect(host.textContent).toContain('post_crta (FIFO 1) → pre_me_rta (FIFO 1) → post_irta (nice 0 (미지정))')
    expect(host.textContent).toContain('순서 고정 · 서로 대기 없음')
    expect(host.textContent).toContain('cpupri')
    await act(async () => root.render(<RtChainCard coupling={coupling({ hw_ms: 30, serial: false })} sched={{}} />))
    expect(host.textContent).toContain('대기에 포함')
    await act(async () => root.render(<RtChainCard coupling={coupling({ order: [] })} sched={{}} />))
    expect(host.textContent).toBe('')
  } finally { act(() => root.unmount()) }
})

it('sweep: the request carries the Timing Budget coupling; changing it marks the result stale until the next run', async () => {
  localStorage.setItem('sdb.cpu.mode', JSON.stringify('sweep'))
  const inputs = vi.spyOn(cpuApi, 'inputs').mockResolvedValue({
    profiles: [{ id: 'p1', scenario_ref: 'uc', variant_ref: 'v', project_ref: null, tasks: [{ task: 'ui', cluster: 'BIG' }] }],
    topologies: [{ id: 'target', version: 1, soc_ref: 'soc-x', clusters: ['BIG'] }],
  })
  const calls: CpuSweepRequest[] = []
  const sweep = vi.spyOn(cpuApi, 'sweep').mockImplementation(async (req) => { calls.push(req); return sweepResult })
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<ChartTipProvider><CpuWhatIfPage ctx={{} as Ctx} /></ChartTipProvider>))
    expect(calls[0].timing_coupling).toBe('stage_slack')
    const off = host.querySelector<HTMLButtonElement>('[aria-label="SW timing 제약 (조건)"] button:nth-child(2)')!
    await act(async () => off.click())
    expect(calls).toHaveLength(1)
    expect(host.querySelector('[aria-label="계산 상태"]')!.textContent).toContain('조건 변경됨')
    await act(async () => [...host.querySelectorAll('button')].find((b) => b.textContent === '변경 반영 계산')!.click())
    expect(calls[1].timing_coupling).toBe('off')
    expect(host.textContent).toContain('비교 기준 (★)')                     // the sweep has a reference choice
  } finally { act(() => root.unmount()); inputs.mockRestore(); sweep.mockRestore(); localStorage.clear() }
})

it('rebalance: no reference choice (always the measured placement), so nothing reruns for it', async () => {
  localStorage.setItem('sdb.cpu.mode', JSON.stringify('rebalance'))
  localStorage.setItem('sdb.cpu.inputs.open', 'true')
  const growth = vi.spyOn(sweepApi, 'run').mockRejectedValue(new Error('growth not under test'))
  const tasks = E2600.units.flatMap((u) => u.tasks.map((t) => ({ task: t, cluster: u.home })))
  const inputs = vi.spyOn(cpuApi, 'inputs').mockResolvedValue({
    profiles: [{ id: 'p1', scenario_ref: null, variant_ref: null, project_ref: null, tasks }],
    topologies: [{ id: 'pmp-e2600', version: 1, soc_ref: 'soc-exynos2600', clusters: ['MID_LF0', 'MID_LF1', 'MID_HF', 'BIG'] }],
  })
  const calls: CpuRebalanceRequest[] = []
  const run = vi.spyOn(rebalanceApi, 'run').mockImplementation(async (req) => { calls.push(req); return { ...E2600, timing_coupling: coupling(), rt_placement: 'cpupri' } })
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<ChartTipProvider><CpuWhatIfPage ctx={{} as Ctx} /></ChartTipProvider>))
    expect(calls).toHaveLength(1)
    expect(host.textContent).not.toContain('비교 기준 (★)')
    expect(host.textContent).toContain('RT chain · 대기 계산 기준')
    expect(host.textContent).toContain('순서 고정 · 서로 대기 없음')
  } finally { act(() => root.unmount()); inputs.mockRestore(); run.mockRestore(); growth.mockRestore(); localStorage.clear() }
})

it('a sweep case is graded like a rebalance split (own slack, then the wait with the class / priority)', () => {
  const base = { feasible: true, slack_ms: { a: 0.5 }, task_ms: { a: 1 } }
  expect(slackVerdict({ ...base, response_prio_ms: { a: 1.2 } }).tier).toBe('ok')
  expect(slackVerdict({ ...base, response_prio_ms: { a: 2 } })).toMatchObject({ tier: 'wait_miss', task: 'a' })
  expect(slackVerdict({ ...base, response_ms: { a: 2 } }).tier).toBe('shared')
})
