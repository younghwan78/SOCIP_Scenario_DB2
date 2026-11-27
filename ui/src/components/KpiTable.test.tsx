// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { KpiCell, KpiTable } from './KpiTable'
import { kpiTitle, type FleetRow, type KpiResult } from '../lib/timingBudget'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

const row = (over: Partial<KpiResult>): KpiResult => ({
  id: null, kpi: 'peak_footprint', metric: null, job: 'still_shot_200m', milestone: null, status: 'no_target',
  value: 2128.4, target: null, bound: null, unit: 'MB', value_source: null, basis: null, sources: ['assumed'], ...over,
})

it('shows value, target and status per KPI', () => {
  const host = document.createElement('div')
  act(() => createRoot(host).render(<KpiTable rows={[
    row({ id: 'heap', status: 'fail', target: 2048, bound: 'max', value_source: 'assumed', basis: 'camera heap' }),
    row({ kpi: 'underrun', job: null, status: 'pass', value: 4.69, target: 0.5, bound: 'min', unit: 'ms', value_source: 'spec' }),
    row({ kpi: 'event_latency', milestone: 'saved', status: 'no_input', value: null }),
  ]} />))
  const cell = (s: string) => host.querySelector(`[data-testid="kpi-${s}"]`)?.textContent ?? ''
  expect(cell('fail')).toContain('≤ 2048 MB')
  expect(cell('fail')).toContain('미달')
  expect(cell('fail')).toContain('가정 목표')
  expect(cell('pass')).toContain('≥ 0.50 ms')
  expect(cell('no_input')).toContain('입력 없음')
})

it('shows the worst fleet KPI status, the passing count and the targets', () => {
  const host = document.createElement('div')
  const fleet = {
    verdict: { status: 'fail', reasons: [], nrt_clock_factor: null, kpis: { status: 'fail', fail: 1, pass: 2 } },
    kpis: [
      { id: 'heap', kpi: 'peak_footprint', metric: null, job: 'still_shot_200m', milestone: null, status: 'fail', value: 2128.4, target: 2048, bound: 'max', unit: 'MB', value_source: 'assumed' },
      { id: 'thumb-200m', kpi: 'event_latency', metric: null, job: 'still_shot_200m', milestone: 'thumbnail', status: 'pass', value: 1399, target: 2000, bound: 'max', unit: 'ms', value_source: 'assumed' },
    ],
  } as unknown as FleetRow
  act(() => createRoot(host).render(<KpiCell r={fleet} />))
  expect(host.querySelector('[data-testid="fleet-kpi-fail"]')?.textContent).toBe('미달 1/2')
  expect(kpiTitle(fleet)).toContain('heap (still_shot_200m): 2128.4 ≤ 2048.0 MB → 미달 (가정 목표)')
  const none = document.createElement('div')
  act(() => createRoot(none).render(<KpiCell r={{ verdict: { status: 'ok', reasons: [], nrt_clock_factor: null } } as unknown as FleetRow} />))
  expect(none.textContent).toBe('—')
})
