// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import type { Ctx } from '../src/App'
import { TimingBudgetPage } from '../src/pages/TimingBudget'
import { timingApi } from '../src/lib/timingBudget'
import { archApi } from '../src/lib/archExplore'
import { PredictionsPage } from '../src/pages/Predictions'

vi.mock('../src/components/TimingCharts', () => ({
  Card: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ClockChart: () => null, Gantt: () => null, Intervals: () => null,
  PowerBw: () => null, SlotBudget: () => null, WhatIf: () => null,
}))
vi.mock('../src/components/ArchCharts', () => ({
  CompositionBars: () => null, RangeBoxes: () => null, SplitBar: () => null,
  SplitLegend: () => null, Waterfall: () => null,
}))
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
const host = document.createElement('div')
let root = createRoot(host)
afterEach(() => { act(() => root.unmount()); root = createRoot(host); vi.restoreAllMocks() })

it('runs the expensive what-if once, without repeating it on each statistic change', async () => {
  // Only request scheduling matters: omit report content to avoid unrelated charts.
  const send = vi.spyOn(timingApi, 'variant').mockImplementation(async (_s, _v, options) => ({
    report: options.include_whatif ? { whatif: [] } : undefined, dvfs_table_ref: null,
  }) as never)
  const ctx = { scenario: 's', variant: 'v', params: {}, navigate: vi.fn() } as unknown as Ctx
  await act(async () => root.render(<TimingBudgetPage ctx={ctx} />))
  expect(send.mock.calls.filter((c) => c[2].include_whatif)).toHaveLength(1)
  await act(async () => root.render(<TimingBudgetPage ctx={{ ...ctx, params: { stat: 'mean' } }} />))
  expect(send.mock.calls.filter((c) => c[2].include_whatif)).toHaveLength(1)
  expect(send).toHaveBeenCalledTimes(3)
})

it('keeps the SW what-if on the selected CPU and throughput models', async () => {
  const send = vi.spyOn(timingApi, 'variant').mockImplementation(async (_s, _v, options) => ({
    report: options.include_whatif ? { whatif: [] } : undefined, dvfs_table_ref: null,
  }) as never)
  vi.spyOn(timingApi, 'dvfsWhatif').mockResolvedValue(null as never)
  const ctx = { scenario: 's', variant: 'v', params: {}, navigate: vi.fn() } as unknown as Ctx
  await act(async () => root.render(<TimingBudgetPage ctx={ctx} />))
  expect(send.mock.calls.find((c) => c[2].include_whatif)?.[2]).toMatchObject({
    cpu_model: 'flat',
  })
  expect(send.mock.calls.find((c) => c[2].include_whatif)?.[2]).not.toHaveProperty('throughput_model')
  await act(async () => root.render(<TimingBudgetPage ctx={{ ...ctx, params: { cpu: 'profile', tp: 'stage' } }} />))
  const whatifs = send.mock.calls.filter((c) => c[2].include_whatif)
  expect(whatifs).toHaveLength(2)
  expect(whatifs[1][2]).toMatchObject({ cpu_model: 'profile', throughput_model: 'stage' })
})

it('selects the correct prediction history when scenarios share a variant name', async () => {
  const row = { variant_id: 'shared', power: { total_mw: 1, cpu_mw: 1, hw_mw: 0, bw_mw: 0 },
    compression: [], dvfs: {}, fps: 30, previous: null, selected_by: 'auto' }
  vi.spyOn(archApi, 'board').mockResolvedValue({ rows: [
    { ...row, id: 'p1', scenario_id: 's1' }, { ...row, id: 'p2', scenario_id: 's2' },
  ] } as never)
  const history = vi.spyOn(archApi, 'history').mockResolvedValue([])
  const ctx = { scenario: 's1', params: { all: '1', v: 'p2' }, navigate: vi.fn() } as unknown as Ctx
  await act(async () => root.render(<PredictionsPage ctx={ctx} />))
  expect(history).toHaveBeenCalledWith('s2', 'shared')
})


it('shows power options of the selected prediction and saves an IQ review decision', async () => {
  const bcrop = 'knob:crop_strategy=byrp_bcrop'
  const result = { key: bcrop, items: [bcrop], labels: ['BYRP bayer crop: byrp_bcrop'], kinds: ['knob'], iq_eval: 'required',
    spec_ok: true, spec_reasons: [], total_mw: 640, delta_mw: -33.8, delta_pct: -5.0, delta_bw_mbs: -300, raw_delta_mw: -51.7,
    raw_delta_pct: -7, attribution: { reference: 'recommended', delta_mw: -33.8, by_category: { 'BW traffic': -40.8, Compression: 17.9, 'IP workload': -10.9 }, factors: [] },
    review_status: 'candidate' }
  const row = { id: 'p1', scenario_id: 'uc-rec', variant_id: 'cam-rec-r1-uhd30-vdis', power: { total_mw: 674, cpu_mw: 300, hw_mw: 130, bw_mw: 244 },
    compression: [], dvfs: {}, fps: 30, previous: null, selected_by: 'auto', eligible_cases: 1,
    power_options: { status: 'ok', notes: [], sets: 1, reference: { rule: 'auto:min-power', case_key: 'k', note: null },
      items: [{ key: bcrop, kind: 'knob', label: 'BYRP bayer crop: byrp_bcrop', value: 'byrp_bcrop', from: 'mcsc_crop', iq_eval: 'required',
        review: { status: 'candidate', scope: null, note: null } }],
      results: [result], best: { key: bcrop, labels: result.labels, delta_mw: -33.8, delta_pct: -5.0, review_status: 'candidate' } } }
  const board = vi.spyOn(archApi, 'board').mockResolvedValue({ rows: [row] } as never)
  vi.spyOn(archApi, 'history').mockResolvedValue([])
  const save = vi.spyOn(archApi, 'setOptionReview').mockResolvedValue({} as never)
  const ctx = { scenario: 'uc-rec', params: { v: 'p1' }, navigate: vi.fn() } as unknown as Ctx
  await act(async () => root.render(<PredictionsPage ctx={ctx} />))
  expect(host.textContent).toContain('-33.8')
  expect(host.querySelector('table[aria-label="option IQ 검토"]')).not.toBeNull()
  expect(host.querySelector('table[aria-label="power option 조합"]')?.textContent).toContain('BW traffic')
  const btn = [...host.querySelectorAll('button')].find((b) => b.textContent === '상태 변경')!
  await act(async () => btn.click())
  const reject = [...host.querySelectorAll('[aria-label="IQ 상태 변경"] button')].find((b) => b.textContent === '기각')!
  const variantOnly = [...host.querySelectorAll('[aria-label="IQ 상태 변경"] button')].find((b) => b.textContent === '이 variant만')!
  await act(async () => { reject.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  await act(async () => { variantOnly.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  const store = [...host.querySelectorAll('[aria-label="IQ 상태 변경"] button')].find((b) => b.textContent === '저장')!
  await act(async () => { store.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  expect(save).toHaveBeenCalledWith({ scenario_id: 'uc-rec', variant_id: 'cam-rec-r1-uhd30-vdis', option_key: bcrop, status: 'rejected', note: undefined })
  expect(board).toHaveBeenCalledTimes(2)  // board refreshed after the decision
})
