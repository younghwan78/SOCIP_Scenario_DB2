// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { VariantDetailBody } from './Explore'
import { archApi, type ExpCase, type RunDetail, type VariantResult } from '../lib/archExplore'
import { calibrationApi } from '../lib/calibration'

vi.mock('../components/ArchCharts', () => ({
  AxisSpread: () => null, BufferSavings: () => <div>buffer savings</div>, CompositionBars: () => null, DomainLevels: () => <div>domain levels</div>,
  IpModes: () => null, RangeBoxes: () => null, SplitBar: () => null, SplitLegend: () => null,
}))
vi.mock('../components/LeverAnalysis', () => ({ LeverAnalysisView: () => <div>lever analysis</div> }))
vi.mock('../components/ExploreTiers', () => ({ TiersView: () => null }))
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

const kase = (key: string, over: Partial<ExpCase> = {}): ExpCase => ({
  key, statistic: 'max', runtime_scale: 1, compression: [], dvfs: { MIF: 3 }, dvfs_raise: 0, total_mw: 1000, cpu_mw: 300, hw_mw: 500,
  bw_mw: 200, bw_mbs: 5000, lossy: false, assumed_ratio: false, verdict: 'ok', eligible: true, ...over,
})
const low = kase('low', { total_mw: 1098.4 })
const robust = kase('robust', { total_mw: 1167.4, dvfs_raise: 2 })
const v: VariantResult = {
  scenario_id: 's', variant_id: 'cam-v', fps: 60, period_ms: 16.7, eis_on: false, mfc_dual: false, spec_ok: true, spec_reasons: [],
  counts: { cases: 10, eligible: 8, sw_slices: 1, compression_sets: 2, dvfs_sets: 5 }, distribution: {} as never,
  baseline: kase('base', { total_mw: 1200 }), recommended: robust, min_power_case: low, alternatives: [low],
  objectives: { order: ['growth', 'power'], growth_target: null, target_met: null, recommended: null, min_power: null, front: [] },
  slices: [], buffers: [], domains: [], axis_spread: {} as never, warnings: [], input_hash: 'h',
  sw_margin: { stages: [], worst: null, growth_tolerance: 1.2, growth_tested_max: 1.3, stat_spread_ms: 0, verdict: 'ok', recommendations: ['keep'] },
}
const run = { id: 'run-1', project_ref: 'p', variants: [v], spec: {} } as unknown as RunDetail

let host: HTMLDivElement
let root: ReturnType<typeof createRoot>
beforeEach(() => {
  host = document.createElement('div'); root = createRoot(host)
  vi.spyOn(archApi, 'board').mockResolvedValue({ rows: [] })
  vi.spyOn(archApi, 'promote').mockResolvedValue({ promoted: [{ id: 'pred-1', total_mw: 1098.4 }], skipped: [] } as never)
  vi.spyOn(calibrationApi, 'coverage').mockResolvedValue({} as never)
})
afterEach(() => { act(() => root.unmount()); vi.restoreAllMocks() })
const button = (text: string) => [...host.querySelectorAll('button')].find((b) => b.textContent === text)!

it('puts the decision first, registers its case by the default rule and keeps the evidence in tabs', async () => {
  await act(async () => root.render(<VariantDetailBody v={v} run={run} readOnly={false} battery={null as never} />))
  const decision = host.querySelector('.decision')!
  expect(decision.textContent).toContain('1098.4 mW · 최저 power (auto:min-power)')
  expect(decision.textContent).toContain('추천 기준(growth → power)의 추천은 다른 조합 (+69.0 mW)')
  // the first thing after the decision is the tab bar, Power open
  expect([...host.querySelectorAll('.evidence-tabs [role=tab]')].map((t) => [t.textContent, t.getAttribute('aria-selected')]))
    .toEqual([['Power', 'true'], ['Timing', 'false'], ['Memory', 'false'], ['DVFS', 'false']])
  const shown = () => [...host.querySelectorAll<HTMLElement>('[role=tabpanel]')].filter((p) => !p.hidden).map((p) => p.getAttribute('aria-label'))
  const panel = (id: string) => host.querySelector<HTMLElement>(`[role=tabpanel][aria-label=${id}]`)!
  expect(shown()).toEqual(['power'])
  expect(panel('power').textContent).toContain('lever analysis')
  expect(panel('timing').textContent).toContain('SW timing margin')
  await act(async () => button('이 조합을 예측으로 등록 (current)').click())
  expect(archApi.promote).toHaveBeenCalledWith('run-1', ['cam-v'], undefined, undefined, 's', 'p', [{ scenario_id: 's', variant_id: 'cam-v', prediction_id: null }])
  // a typed reason survives a look at another tab: the panels stay mounted
  const reason = host.querySelector<HTMLInputElement>('input.input')!
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(reason, 'thermal headroom')
    reason.dispatchEvent(new Event('input', { bubbles: true }))
  })
  act(() => button('Timing').click())
  expect(shown()).toEqual(['timing'])
  act(() => button('DVFS').click())
  expect(shown()).toEqual(['dvfs'])
  expect(panel('dvfs').textContent).toContain('domain levels')
  act(() => button('Power').click())
  expect(host.querySelector<HTMLInputElement>('input.input')!.value).toBe('thermal headroom')
})

it('marks the lowest-power case, not the objective recommendation, as the default in the case table', async () => {
  await act(async () => root.render(<VariantDetailBody v={v} run={run} readOnly={false} battery={null as never} />))
  const ranks = [...host.querySelectorAll('tbody tr')].map((tr) => tr.querySelectorAll('td')[1]?.textContent)
  expect(ranks.slice(0, 2)).toEqual(['최저 power', '추천 (추천 기준)'])
  // the default pick is the server default: registering it needs no reason
  const radio = host.querySelectorAll<HTMLInputElement>('tbody input[type=radio]')
  expect(radio[0].checked).toBe(true)
})
