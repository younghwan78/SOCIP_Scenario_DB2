// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { MeasurePopover, PowerChip } from './MeasurePopover'
import { calibrationApi, type MeasDetail } from '../lib/calibration'
import { archApi, type BoardRow } from '../lib/archExplore'
import { api } from '../lib/api'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
afterEach(() => vi.restoreAllMocks())
const detail = {
  id: 'MEAS-0123456789abcdef', scenario_id: 's', variant_id: 'v', project_ref: 'p', measured_at: '2026-10-01T10:00:00', context: { silicon_rev: 'EVT1', thermal: 'cold' },
  total: { mean: 790, std: 12, p95: null, ci_95: null, n: 3 }, fps: 29.97, synthetic: false, frame_latency: { mean: 80, p95: 95 },
  measured: { categories: { cpu: 300, ip: 250, bw: 200, other: 40 }, category_std: { cpu: 5, ip: 4, bw: 3, other: 1 }, rail_total_mw: 790,
    rails: [{ rail: 'VDD_CAM', category: 'ip', power_mw: 250, std_mw: 4, voltage_v: 0.75, current_ma: null, domain: 'CAM' }] },
  rail_domain_map_ref: 'rails-v1', unexplained_mw: 0, origin: 'physical_capture',
  predictions: [{ kind: 'current', id: 'PRED-1', label: '등록', total_mw: 812, delta_pct: 2.8, split: { cpu: 310, ip: 260, bw: 242 },
    rows: [{ category: 'cpu', prediction_mw: 310, measurement_mw: 300, delta_mw: 10, delta_pct: 3.3 }, { category: 'ip', prediction_mw: 260, measurement_mw: 250, delta_mw: 10, delta_pct: 4 },
      { category: 'bw', prediction_mw: 242, measurement_mw: 200, delta_mw: 42, delta_pct: 21 }, { category: 'other', prediction_mw: null, measurement_mw: 40, delta_mw: null, delta_pct: null }],
    conditions: { overall: 'reference', items: [{ item: 'sw_baseline_ref', measured: 'SW2', predicted: 'SW1', status: 'mismatch' }] } }],
  sw_tasks: [{ task: 'camera_hal', mean_ms: 4.2, p95_ms: 5.1, cluster: 'MID_LF' }],
} as unknown as MeasDetail
async function render(el: React.ReactElement) {
  const host = document.createElement('div'); document.body.appendChild(host)
  const root = createRoot(host)
  await act(async () => root.render(el))
  return { host, root }
}

it('shows the measurement at basis-popover depth and links to the evidence page', async () => {
  vi.spyOn(calibrationApi, 'detail').mockResolvedValue(detail)
  vi.spyOn(api, 'simConfigs').mockResolvedValue({ items: [] } as never)
  const go = vi.fn()
  const { host, root } = await render(<MeasurePopover measId={detail.id} at={{ x: 10, y: 10 }} onClose={() => undefined} onEvidence={go} />)
  try {
    const text = host.textContent ?? ''
    expect(text).toContain('790.0 mW')
    expect(text).toContain('232 mA')                                   // 790 / 4.0 / 0.85
    expect(text).toContain('+21.0%')                                   // BW prediction error per category
    expect(text).toContain('참고 비교 (조건 불일치)')
    expect(text).toContain('sw_baseline_ref: 실측 SW2 / 예측 SW1')
    expect(text).toContain('camera_hal')
    await act(async () => [...host.querySelectorAll('button')].find((b) => b.textContent?.includes('전체 보기'))!.click())
    expect(go).toHaveBeenCalled()
  } finally { act(() => root.unmount()) }
})
it('pipeline chip shows registered vs measured power and opens both in one popover', async () => {
  const row = { id: 'PRED-1', variant_id: 'v', power: { total_mw: 812, cpu_mw: 310, hw_mw: 260, bw_mw: 242 }, bw_mbs: 5327, fps: 30, verdict: 'ok', dvfs: { CAM: 7 }, compression: [], selection_rule: 'iq_keep', selected_by: 'auto', created_at: '2026-10-10T00:00:00', previous: null } as unknown as BoardRow
  vi.spyOn(archApi, 'board').mockResolvedValue({ rows: [row] })
  vi.spyOn(calibrationApi, 'coverage').mockResolvedValue({ v: { simulation: 0, measurement: 1, synthetic: 0, current_prediction: null, measurements: [{ id: detail.id, at: '2026-10-01', origin: 'physical_capture', synthetic: false, total_mw: 790, shown: true }] } })
  vi.spyOn(calibrationApi, 'detail').mockResolvedValue(detail)
  vi.spyOn(api, 'simConfigs').mockResolvedValue({ items: [] } as never)
  const { host, root } = await render(<PowerChip scenarioId="s" variantId="v" project="p" />)
  try {
    const chip = host.querySelector<HTMLButtonElement>('.power-chip')!
    expect(chip.textContent).toContain('예측 812 · 실측 790 mW')
    expect(chip.textContent).toContain('+2.8%')
    await act(async () => chip.click())
    const text = host.textContent ?? ''
    expect(text).toContain('등록 예측')
    expect(text).toContain('CPU 310.0 · IP 260.0 · BW 242.0 mW')
    expect(text).toContain('5327 MB/s')
    expect(text).toContain('CPU · IP · BW 예측 vs 실측')
  } finally { act(() => root.unmount()) }
})

it('shows condition differences for the latest simulation even when the registered prediction matches', async () => {
  const current = { ...detail.predictions[0], conditions: { overall: 'equivalent' as const, items: [] } }
  const simulation = { ...detail.predictions[0], id: 'SIM-1', kind: 'simulation' as const }
  vi.spyOn(calibrationApi, 'detail').mockResolvedValue({ ...detail, predictions: [current, simulation] })
  vi.spyOn(api, 'simConfigs').mockResolvedValue({ items: [] } as never)
  const { host, root } = await render(<MeasurePopover measId={detail.id} at={{ x: 10, y: 10 }} onClose={() => undefined} />)
  try {
    expect(host.textContent).toContain('Sim 최신: 참고 비교 (조건 불일치)')
    expect(host.textContent).toContain('sw_baseline_ref: 실측 SW2 / 예측 SW1')
  } finally { act(() => root.unmount()) }
})
