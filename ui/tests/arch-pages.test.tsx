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
