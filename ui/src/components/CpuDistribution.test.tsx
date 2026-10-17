// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { OppGauge, RatioCurves } from './CpuDistribution'
import { CpuReviewSnapshotCard } from './CpuReviewSnapshot'
import { ChartTipProvider } from './ChartTip'
import { cpuSnapshotApi } from '../lib/reviewCpu'
import { firstStepUp, sweepYMax, type GrowthSweep } from '../lib/growthSweep'
import type { CpuRebalance } from '../lib/rebalance'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
if (typeof ResizeObserver === 'undefined') Object.assign(globalThis, { ResizeObserver: class { observe() {} unobserve() {} disconnect() {} } })
afterEach(() => { vi.restoreAllMocks(); localStorage.clear() })

const split = (mhz: Record<string, number>, total: number) => ({ assign: {}, moved: [], total_mw: total, delta_mw: 0, feasible: true, mw: {}, mhz, mv: {}, knobs: [] })
const rb = {
  pool: ['LF0', 'LF1'], clusters: [{ name: 'LF0', core_type: 'MID', cores: 3, in_pool: true, opps_mhz: [400, 1000, 1600], capacity: 350 },
    { name: 'LF1', core_type: 'MID', cores: 3, in_pool: true, opps_mhz: [400, 1000, 1600], capacity: 350 }],
  reference: split({ LF0: 1600, LF1: 400, dsu: 600 }, 240), best: split({ LF0: 1000, LF1: 400, dsu: 600 }, 230),
  boundaries: { reference: [{ cluster: 'LF0', mhz: 1600, mv: 720, peak_cpu_util: 150, capacity: 350, next_lower_mhz: 1000, next_lower_mv: 650, delta_util_needed: 12.7 }], best: [] },
  ratio_curves: [{ target: 'LF1', start_util_pct: 20, best_index: 1, points: [
    { util_pct: 20, moved_unit: null, total_mw: 240, feasible: true, mhz: { LF0: 1600, LF1: 400, dsu: 600 } },
    { util_pct: 35, moved_unit: 'eis', total_mw: 220, feasible: true, mhz: { LF0: 1000, LF1: 400, dsu: 600 } },
    { util_pct: 60, moved_unit: 'hal', total_mw: 250, feasible: false, mhz: { LF0: 1000, LF1: 1000, dsu: 600 } }] }],
} as unknown as CpuRebalance
const sweep = { points: [{ growth: 1, reference: split({ LF0: 1600 }, 240), strategies: [] }, { growth: 1.3, reference: split({ LF0: 2000 }, 380), strategies: [] }],
  events: [{ which: 'reference', growth_from: 1.2, growth_to: 1.3, cluster: 'LF0', mhz: [1600, 2000], delta_mw: 135 }],
  limits: { opp_step: null, opp_step_best_mw: null, timing_at: null, tolerance: 1.2, binding: 'opp' }, elapsed_ms: 1 } as unknown as GrowthSweep

async function render(el: JSX.Element) {
  const host = document.createElement('div'); document.body.appendChild(host)
  await act(async () => { createRoot(host).render(<ChartTipProvider>{el}</ChartTipProvider>) })
  return host
}

it('ratio curve, OPP gauge and helpers', async () => {
  const rc = await render(<RatioCurves r={rb} />)
  expect(rc.textContent).toContain('→ LF1')
  expect(rc.textContent).toContain('최저 35% 220.0 mW')
  const g = await render(<OppGauge r={rb} sweep={sweep} />)
  expect(g.textContent).toContain('12.7')
  expect(g.textContent).toContain('×1.3: 1600→2000')
  expect(firstStepUp(sweep, 'LF0')?.growth_to).toBe(1.3)
  expect(sweepYMax([sweep, null])).toBe(380)
})

it('records the sweep for the review and lists snapshots', async () => {
  const snap = { id: 'S1', project_ref: 'p', scenario_id: 's', variant_id: 'cam-rec-v', profile_ref: 'm', power_params_ref: 'pmp', base_power_params_ref: null,
    status: 'active' as const, note: null, created_by: 'u', created_at: '2026-10-18T00:00', summary: { tolerance: 1.1, binding: 'timing' as const, timing_at: 1.1,
      opp_step: null, opp_step_best_mw: null, growth_range: [1, 1.5] as [number, number], points: [], best_at_start: { total_mw: 1, moved: [], delta_mw: -4.8 } } }
  vi.spyOn(cpuSnapshotApi, 'list').mockResolvedValue([snap])
  const onRecord = vi.fn().mockResolvedValue(snap)
  const host = await render(<CpuReviewSnapshotCard projectRef="p" scenarioId="s" variantId="cam-rec-v" canRecord onRecord={onRecord} />)
  expect(host.textContent).toContain('×1.1')
  const btn = [...host.querySelectorAll('button')].find((b) => b.textContent === '갱신') as HTMLButtonElement
  await act(async () => { btn.click() })
  expect(onRecord).toHaveBeenCalled()
  expect(host.textContent).toContain('포함됨')
})
