// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { ClockLatency, RailDrill, SwCompare } from './CalibrationDrill'
import type { Drilldown } from '../lib/calibration'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

const d: Drilldown = {
  rails: {
    groups: [
      { key: 'bw', label: 'BW (MIF + DRAM)', category: 'bw', meas_mw: 100, pred_mw: 200, delta_mw: 100, delta_pct: 100, share_pct: 60, note: null, rails: [{ rail: 'VDDMIF', mw: 100 }], pred_items: [] },
      { key: 'ip:VDD_INT', label: 'VDD_INT', category: 'ip', meas_mw: 90, pred_mw: 20, delta_mw: -70, delta_pct: -77.8, share_pct: 40, note: null, rails: [{ rail: 'B4S4_VDD_INT_L', mw: 90 }], pred_items: [{ name: 'mtnr', mw: 15, vdd: 'VDD_INTCAM' }] },
    ],
    notes: ['VDD_INTCAM 예측은 별도 실측 rail이 없어 VDD_INT rail에 합산'], cpu_clusters: [], vdd_source: 'sim-1',
  },
  latency: { pred_ms: 44, meas_p95_ms: 35, meas_mean_ms: 31, delta_pct: 25.7 },
  sw_stage: 'nrt', sw_budget_ms: 25, statistic: 'max',
  sw: { statistic: 'max', budget_ms: 25, optimistic: 1, compared: 1, worst: null,
    rows: [{ task: 'post_irta', assumed_ms: 4, assumed_stat: 'max', mean_ms: 3.8, p95_ms: 5.2, max_ms: 6.4, delta_ms: 1.2, delta_pct: 30, assumed_margin_pct: 84, measured_margin_pct: 79, status: 'under_assumed' }] },
  clock: [{ group: 'CAM', pred_mhz: 133, dvfs_level: 7, nodes: 8, meas_mhz: null, meas_p50_mhz: null, delta_pct: null }],
}

async function render(el: JSX.Element) {
  const host = document.createElement('div')
  document.body.appendChild(host)
  await act(async () => { createRoot(host).render(el) })
  return host
}

it('rail drill-down lists groups by error and expands rails / predicted items', async () => {
  const host = await render(<RailDrill d={d} />)
  const rows = [...host.querySelectorAll('tbody > tr')]
  expect(rows[0].textContent).toContain('BW (MIF + DRAM)')
  expect(host.textContent).toContain('VDD_INTCAM 예측은')
  await act(async () => { (rows[1] as HTMLElement).click() })
  expect(host.textContent).toContain('B4S4_VDD_INT_L')
  expect(host.textContent).toContain('mtnr')
})

it('SW compare marks tasks longer than the assumption; latency row shows p95', async () => {
  const sw = await render(<SwCompare d={d} />)
  expect(sw.textContent).toContain('가정 초과')
  expect(sw.textContent).toContain('가정보다 긴 task 1/1')
  const cl = await render(<ClockLatency d={d} />)
  expect(cl.textContent).toContain('p95 35.0')
  expect(cl.textContent).toContain('residency 없음')
})
