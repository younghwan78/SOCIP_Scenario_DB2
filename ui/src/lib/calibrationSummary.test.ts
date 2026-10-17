import { describe, expect, it } from 'vitest'
import { absGapMw, band, groupOf, sortRows, waterfall, type SummaryRow } from './calibrationSummary'

const row = (v: string, fps: number, total: number, worst: number, gap: [number, number, number]): SummaryRow => ({
  scenario_id: 's', variant_id: v, measurement_id: `m-${v}`, measured_at: null, origin: 'synthetic', synthetic: true, captures: 1, fps,
  meas: { total: 600, cpu: 200, ip: 200, bw: 150, other: 50 },
  pred: { id: 'p', total: 540, cpu: 200 - gap[0], ip: 200 - gap[1], bw: 150 - gap[2] },
  delta_pct: { total, cpu: worst, ip: 0, bw: 0 }, fit: { worst_category: 'cpu', worst_delta_pct: worst, offsetting: false }, conditions: null,
})

describe('calibration summary helpers', () => {
  it('groups variants by name and fps', () => {
    expect(groupOf('cam-rec-r1-uhd30-vdis', 29.97)).toBe('UHD 30')
    expect(groupOf('cam-rec-r1-fhd60-sdr', 59.94)).toBe('60 fps')
    expect(groupOf('cam-rec-r1-8k30-psm', 30)).toBe('8K')
    expect(groupOf('cam-rec-r1-uhd120', 120)).toBe('고속 (≥ 100 fps)')
    expect(groupOf('cam-rec-pip-fhd30', 23)).toBe('멀티 카메라')
    expect(groupOf('pipe-x', 30)).toBe('기타')
  })
  it('bands and sorts', () => {
    expect([band(9.9), band(-25), band(25.1), band(null)]).toEqual(['ok', 'warn', 'fail', ''])
    const rows = [row('cam-rec-a-fhd30', 30, -5, 10, [10, 0, 0]), row('cam-rec-b-uhd30', 30, -30, 60, [100, -50, 0])]
    expect(sortRows(rows, 'worst')[0].variant_id).toBe('cam-rec-b-uhd30')
    expect(sortRows(rows, 'group')[0].variant_id).toBe('cam-rec-a-fhd30')
    expect(absGapMw(rows[1])).toBe(100 + 50 + 0 + 50)
  })
  it('waterfall bridges the registered prediction to the measured total', () => {
    const wf = waterfall({
      total: { mean: 675.2, std: null, p95: null, ci_95: null, n: 3 },
      measured: { categories: { cpu: 264.6, ip: 202.6, bw: 149.8, other: 58.2 }, category_std: { cpu: 0, ip: 0, bw: 0, other: 0 }, rail_total_mw: 675.2, rails: [] },
      predictions: [{ kind: 'current', id: 'p', label: '', total_mw: 549.8, delta_pct: -18.6, split: null,
        rows: [{ category: 'cpu', prediction_mw: 113.5 }, { category: 'ip', prediction_mw: 164.4 }, { category: 'bw', prediction_mw: 271.9 }] as never }],
    })!
    expect(wf.steps.map((s) => s.label)).toEqual(['등록 예측', 'CPU', 'IP', 'BW', '미모델', '실측'])
    expect(wf.steps[1].value).toBeCloseTo(151.1, 1)
    expect(wf.steps[3].value).toBeCloseTo(-122.1, 1)
    expect(wf.steps[4].to).toBeCloseTo(675.2, 1)
    expect(wf.offsetShare).toBeGreaterThan(0.6)
  })
})
