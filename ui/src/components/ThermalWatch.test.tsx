import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { ThermalWatchView } from './ThermalWatch'
import { DEFAULT_BATTERY } from '../lib/battery'
import type { ThermalWatch } from '../lib/review'

const data: ThermalWatch = {
  project_ref: 'p', policy: { throughput_model: 'pipelined', register_baseline: 'iq_keep', max_latency_frames: null, power_reference: null, thermal_watch: [] } as never,
  items: [{
    scenario_id: 's', variant_id: 'uhd120', label: 'UHD120', note: null, prediction_id: 'x', run_id: 'r', current_mw: 2000, baseline: 'iq_keep',
    registered_mw: 2000, registered_lossy: false, throughput_model: 'pipelined', verdict: 'ok', reference: null, notes: [],
    menu: [
      { key: 'mode:mtnr=LowPower', label: 'MTNR LP', kind: 'option', feasible: true, cost: 'IQ 승인 완료', delta_mw: -50, exclusive: 'mode:mtnr', iq_status: 'adopted' },
      { key: 'knob:l0=skip', label: 'L0 skip', kind: 'option', feasible: false, cost: 'IQ 반려 — 사용 불가', delta_mw: -100, exclusive: 'knob:l0', iq_status: 'rejected' },
    ],
    plans: [{ ask_pct: 10, need_mw: -200, picked: ['mode:mtnr=LowPower'], saving_mw: -50, achieved: false, iq_cost: true, iq_pending: [] }],
    approved_plans: [{ ask_pct: 10, need_mw: -200, picked: ['mode:mtnr=LowPower'], saving_mw: -50, achieved: false, iq_cost: true, iq_pending: [], scope: 'approved' }],
    trades: [{ variant_id: 'uhd60', total_mw: 1000, delta_mw: -1000, delta_pct: -50, changes: [{ key: 'fps', from: 120, to: 60 }], verdict: 'ok', prediction_id: 'y', also: ['uhd60-b'] }],
  }],
}

it('shows IQ review status, the approved-only plan and performance trades (EXP-04/06)', () => {
  const html = renderToStaticMarkup(createElement(ThermalWatchView, { data, battery: DEFAULT_BATTERY }))
  expect(html).toContain('IQ 승인')
  expect(html).toContain('IQ 반려')
  expect(html).toContain('조합 검증 필요')
  expect(html).toContain('성능 trade 후보')
  expect(html).toContain('fps 120→60')
  expect(html).toContain('uhd60 +1')
})
