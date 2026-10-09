import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { MeasuredCompareCard, MeasuredPicker, conditionChips, measuredChip } from './TimingWorkbench'
import { formatMeasuredFlags, parseMeasured } from '../lib/timingBudget'
import { conditionParams, conditionText, type BoardRow } from '../lib/archExplore'
import { DEFAULT_BATTERY } from '../lib/battery'

it('round-trips measured inputs through the URL', () => {
  expect(parseMeasured('meas-1', 'sw,cpu')).toEqual({ measurement_ref: 'meas-1', sw: true, clock: false, cpu: true })
  expect(parseMeasured('', 'sw')).toBeNull()
  expect(formatMeasuredFlags({ measurement_ref: 'm', sw: true, clock: true })).toBe('sw,clock')
  expect(formatMeasuredFlags({ measurement_ref: 'm' })).toBeUndefined()
  expect(measuredChip({ measurement_ref: 'm', sw: true, cpu: true })).toBe('실측 입력 SW·CPU')
  expect(measuredChip({ measurement_ref: 'm' })).toBe('실측 비교만')
})

const opt = { id: 'meas-1', measured_at: '2026-09-25T01:00:00Z', synthetic: true, origin: 'synthetic', total_mw: 1966, sw_tasks: ['post_irta'], clock_ips: 0, cpu: false, context: {} }
it('enables only the inputs the measurement can supply', () => {
  const html = renderToStaticMarkup(createElement(MeasuredPicker, { options: [opt], value: { measurement_ref: 'meas-1', sw: true }, onChange: () => {} }))
  expect(html).toContain('합성 2026-09-25 · 1966 mW')
  const boxes = html.match(/<input type="checkbox"[^>]*>/g) ?? []
  expect(boxes).toHaveLength(3)
  expect(boxes[0]).not.toContain('disabled')          // SW available
  expect(boxes[1]).toContain('disabled')              // no clock observations
  expect(boxes[2]).toContain('disabled')              // no CPU profile
  expect(renderToStaticMarkup(createElement(MeasuredPicker, { options: [], value: null, onChange: () => {} }))).toContain('실측 없음')
})

it('compares the condition with the measurement per rail category', () => {
  const html = renderToStaticMarkup(createElement(MeasuredCompareCard, { battery: DEFAULT_BATTERY, data: {
    measurement_ref: 'meas-1', measured_at: '2026-09-25', synthetic: true, origin: 'synthetic', context: { silicon_rev: 'EVT1' }, inputs: { sw: true, clock: false, cpu: false },
    total: { prediction_mw: 2088, measurement_mw: 1966, delta_pct: 6.2, delta_mw: 122 },
    rows: [{ category: 'cpu', prediction_mw: 303, measurement_mw: 623, delta_mw: -320, delta_pct: -51.4 }, { category: 'other', prediction_mw: null, measurement_mw: 65, delta_mw: null, delta_pct: null }],
    unexplained_mw: 0, fps: null, frame_latency: null, sw_tasks: [] } }))
  expect(html).toContain('실측 입력: SW runtime')
  expect(html).toContain('+6.2%')
  expect(html).toContain('-51.4%')
  expect(html).toContain('미모델')
})

it('keeps measured inputs in the condition chips and when re-opening a registration', () => {
  expect(conditionChips({ statistic: 'max', scale: 1, eis: 'auto', cpuModel: 'flat', throughput: 'pipelined', margin: 0.25, profile: null, overrides: {}, measured: { measurement_ref: 'm', clock: true } })).toContain('실측 입력 clock')
  const row = { scenario_id: 's', variant_id: 'v', condition: { source: 'timing-budget', statistic: 'max', runtime_scale: 1, throughput_model: 'pipelined', eis: 'auto', cpu_model: 'flat',
    rt_margin: 0.25, output_margin: 0.25, config_profile_ref: null, dvfs_overrides: {}, dvfs: {}, compression: [],
    measured: { ref: 'meas-1', inputs: { sw: true, clock: false, cpu: false }, sw: ['post_irta'], clock_ref: null, cpu_ref: null } } } as unknown as BoardRow
  expect(conditionParams(row)).toMatchObject({ mref: 'meas-1', min: 'sw' })
  expect(conditionText(row.condition)).toContain('실측 SW')
})
