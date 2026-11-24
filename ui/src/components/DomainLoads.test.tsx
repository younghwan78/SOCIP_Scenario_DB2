// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { DomainLoads } from './TimingCharts'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

it('shows the operating point, busy share and the assumed mark of each domain load', () => {
  const el = document.createElement('div')
  act(() => createRoot(el).render(
    <DomainLoads loads={{
      gpu: { model: 'util-vf-v1', work_mcycles_s: 240, freq_mhz: 298, freq_by: 'governor', f_max_mhz: 980, mv: 637, util: 0.805,
        target_util: 0.85, dynamic_mw: 1301, static_mw: 24, mw: 1325, feasible: true, value_source: 'assumed' },
      abox: { model: 'util-vf-v1', work_mcycles_s: 20, freq_mhz: 400, freq_by: 'fixed', f_max_mhz: 1500, mv: 600, util: 0.05,
        target_util: 0.85, dynamic_mw: 1.1, static_mw: 2, mw: 3.1, feasible: true, value_source: 'assumed' },
    }} />))
  const text = el.textContent ?? ''
  expect(text).toContain('GPU: 240 Mcycle/s → 298 MHz (governor) · util 81%')
  expect(text).toContain('ABOX: 20 Mcycle/s → 400 MHz (고정)')
  expect(text.match(/가정/g)?.length).toBe(2)
})

it('shows a subsystem by its unit total and marks unattributed units as a lower bound', () => {
  const el = document.createElement('div')
  act(() => createRoot(el).render(
    <DomainLoads loads={{
      abox: { model: 'mcps-v1', mw: 5.08, feasible: true, freq_mhz: 200, util: 0.125, value_source: 'assumed',
        unattributed_units: ['uaif0'] },
    }} />))
  const text = el.textContent ?? ''
  expect(text).toContain('ABOX: subsystem (MCPS) → 200 MHz · 최대 util 13%')
  expect(text).toContain('unit 합 5.1 mW (미산정 uaif0: 하한)')
  expect(text).not.toContain('dynamic')
})
