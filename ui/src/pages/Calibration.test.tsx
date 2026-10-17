// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import type { Ctx } from '../App'
import { calibrationApi, type MeasRow } from '../lib/calibration'
import { summaryApi, type CalSummary } from '../lib/calibrationSummary'
import { CalibrationPage } from './Calibration'
import { ChartTipProvider } from '../components/ChartTip'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
if (typeof ResizeObserver === 'undefined') Object.assign(globalThis, {
  ResizeObserver: class { observe() {} unobserve() {} disconnect() {} },
})
afterEach(() => { vi.restoreAllMocks(); localStorage.clear() })

it('applies the synthetic filter to summary metrics and closes a filtered capture detail', async () => {
  const measurements = vi.spyOn(calibrationApi, 'measurements').mockResolvedValue([{
    id: 'synthetic', scenario_id: 's', variant_id: 'v', synthetic: true, total: { mean: 100 }, rails: 0,
    current_prediction: null, simulation: null,
  } as MeasRow])
  const summary = vi.spyOn(summaryApi, 'get').mockResolvedValue({ rows: [], coverage: { compared: 0 } } as unknown as CalSummary)
  const detail = vi.spyOn(calibrationApi, 'detail').mockResolvedValue(null as never)
  const ctx = { project: 'p', scenario: 's', variant: 'v', params: { all: '1', caps: '1', m: 'synthetic' },
    navigate: vi.fn() } as unknown as Ctx
  const host = document.createElement('div'), root = createRoot(host)
  const page = (value: Ctx) => <ChartTipProvider><CalibrationPage ctx={value} /></ChartTipProvider>
  try {
    await act(async () => root.render(page(ctx)))
    expect(measurements).toHaveBeenCalledWith(undefined, 'p')
    expect(summary).toHaveBeenLastCalledWith({ projectRef: 'p', includeSynthetic: true })
    expect(detail).toHaveBeenCalledWith('synthetic')
    detail.mockClear()
    await act(async () => root.render(page({ ...ctx, params: { ...ctx.params, real: '1' } })))
    expect(summary).toHaveBeenLastCalledWith({ projectRef: 'p', includeSynthetic: false })
    expect(detail).not.toHaveBeenCalled()
    expect(host.textContent).toContain('실제 측정 evidence가 없습니다')
  } finally { act(() => root.unmount()) }
})
