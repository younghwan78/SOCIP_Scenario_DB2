// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { PowerBw } from './TimingCharts'
import type { TimingReport } from '../lib/timingBudget'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
if (typeof ResizeObserver === 'undefined') Object.assign(globalThis, { ResizeObserver: class { observe() {} unobserve() {} disconnect() {} } })

const report = (residency?: number) => ({
  power: {
    total_mw: 55.4 + (residency ?? 0), cpu_mw: 52.5, hw_mw: 2.9, bw_mw: 0, bw_hw_mw: 0, bw_sw_mw: 0,
    share_pct: { cpu: 0, hw: 0, bw: 0 }, hw_by_ip: { abox: 2.9 }, cpu_by_task: { sw_decoder: 52.5 }, cpu_busy_ms: 1,
    cpu_model: { cluster: 0, freq_mhz: 1000, volt_v: 0.7, source: 'assumed' }, zero_power_ips: [],
    ...(residency != null ? { residency_mw: residency } : {}),
  },
  bw: { total_mbs: 0, hw_mbs: 0, sw_mbs: 0, hw_by_ip: {}, sw_by_task: {}, share_pct: { hw: 0, sw: 0 } },
  dvfs: { applied: false, tables: [] },
}) as unknown as TimingReport

it('shows wake residency as a fourth power part only when it was computed', () => {
  const el = document.createElement('div')
  act(() => createRoot(el).render(<PowerBw report={report(50)} />))
  expect(el.textContent).toContain('Wake residency')
  expect(el.textContent).toContain('CPU + HW IP core + BW(MIF) + wake residency')
  expect([...el.querySelectorAll('svg[aria-label="전력 구성"] rect')].length).toBe(4)
  const plain = document.createElement('div')
  act(() => createRoot(plain).render(<PowerBw report={report()} />))
  expect(plain.textContent).not.toContain('Wake residency')
  expect([...plain.querySelectorAll('svg[aria-label="전력 구성"] rect')].length).toBe(3)
})
