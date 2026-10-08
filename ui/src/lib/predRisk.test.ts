import { describe, expect, it } from 'vitest'
import { assessAll, assessRisk, minSlackPct } from './predRisk'
import type { BoardRow } from './archExplore'

const row = (o: Partial<BoardRow> & { id: string; total?: number; cpu?: number; hw?: number; bw?: number }): BoardRow => ({
  scenario_id: 's', variant_id: o.id, status: 'current', run_id: 'r', run_title: null, run_created_at: null, case_key: 'k', selection_rule: 'auto:min-power',
  selected_by: 'auto', reason: null, created_at: null, fps: 30, bw_mbs: 3000, distribution: null, compression: [], dvfs: {}, verdict: 'ok',
  eligible_cases: 10, alternatives: 0, verified: null, statistic: 'max', runtime_scale: 1, previous: null,
  power: { total_mw: o.total ?? 600, cpu_mw: o.cpu ?? 100, hw_mw: o.hw ?? 300, bw_mw: o.bw ?? 200 }, ...o,
} as BoardRow)

describe('prediction risk', () => {
  it('flags timing fail as high and points at Timing Budget', () => {
    const r = assessRisk(row({ id: 'a', verdict: 'fail' }), { target_mw: null })
    expect(r.level).toBe('high')
    expect(r.risks[0].kind).toBe('perf')
    expect(r.focus.some((f) => f.page === 'timing')).toBe(true)
  })
  it('judges power against the customer target', () => {
    expect(assessRisk(row({ id: 'a', total: 1100 }), { target_mw: 1000 }).gap_mw).toBe(100)
    expect(assessRisk(row({ id: 'a', total: 1100 }), { target_mw: 1000 }).level).toBe('high')
    expect(assessRisk(row({ id: 'a', total: 950 }), { target_mw: 1000 }).level).toBe('med')
    expect(assessRisk(row({ id: 'a', total: 500 }), { target_mw: 1000 }).level).toBe('ok')
  })
  it('names the dominant power component as the first lever', () => {
    expect(assessRisk(row({ id: 'a', total: 600, cpu: 400, hw: 100, bw: 100 }), { target_mw: null }).focus[0].page).toBe('cpu')
    expect(assessRisk(row({ id: 'a', total: 600, cpu: 50, hw: 100, bw: 450 }), { target_mw: null }).dominant.part).toBe('BW')
  })
  it('lowers confidence without a real measurement and keeps option gains first', () => {
    const r = assessRisk(row({ id: 'a', total: 980, power_options: { status: 'ok', notes: [], items: [], results: [], best: { key: 'x', labels: ['L0 skip'], delta_mw: -30, delta_pct: -3, review_status: 'pending' } } as unknown as BoardRow['power_options'] }),
      { target_mw: 1000, measured: new Map() })
    expect(r.risks.some((x) => x.kind === 'confidence')).toBe(true)
    expect(r.focus[0]).toMatchObject({ lever: 'option', gain_mw: -30 })
  })
  it('computes SW slack from the frozen stages and sorts by risk', () => {
    const slack = row({ id: 'b', verdict_detail: { status: 'ok', reasons: [], nrt_clock_factor: null, derived: false, period_ms: 33.3, intervals: {},
      stages: [{ id: 'nrt', budget_ms: 13.3, sw_ms: 20, hw_ms: 11 }] } })
    expect(minSlackPct(slack)).toBeCloseTo((2.3 / 33.3) * 100, 1)
    const all = assessAll([row({ id: 'a' }), slack, row({ id: 'c', verdict: 'fail' })], { target_mw: null })
    expect(all.map((x) => x.row.id)).toEqual(['c', 'b', 'a'])
  })
})
