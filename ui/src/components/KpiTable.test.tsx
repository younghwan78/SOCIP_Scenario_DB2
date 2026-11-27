// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { KpiTable } from './KpiTable'
import type { KpiResult } from '../lib/timingBudget'

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
