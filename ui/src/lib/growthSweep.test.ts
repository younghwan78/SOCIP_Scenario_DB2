import { describe, expect, it } from 'vitest'
import { growthGrid, spreadVsConcentrate, strategyMatrix, sweepStageTip, type SweepPoint } from './growthSweep'

const pt = (g: number, strat: [string, string[], number, boolean][]): SweepPoint => ({
  growth: g, reference: { total_mw: 1, feasible: true, mhz: { A: 1, dsu: 1 }, mw: {}, moved: [] }, best: null,
  strategies: strat.map(([kind, clusters, total_mw, feasible]) => ({ kind: kind as 'spread', clusters, total_mw, feasible, mhz: {} })),
  winner: null, big_gain_mw: null, cpu_bw_mbs: null, feasible_count: null, stages: [],
})

describe('growth sweep helpers', () => {
  it('builds a bounded grid', () => {
    expect(growthGrid(1, 1.5, 0.1)).toEqual([1, 1.1, 1.2, 1.3, 1.4, 1.5])
    expect(growthGrid(1, 3, 0.1)).toHaveLength(13)
    expect(growthGrid(1, 3, 0.1)[12]).toBe(3)
    expect(growthGrid(1, 1.25, 0.2)).toEqual([1, 1.2, 1.25])
    expect(growthGrid(1, 1.26, 0.2)).toEqual([1, 1.2, 1.26])
    expect(growthGrid(1, 1.1, 0.5)).toEqual([1, 1.1])
    expect(growthGrid(1, 1, 0.1)).toEqual([1, 1.1])
  })
  it('makes a growth × strategy matrix with the feasible row minimum', () => {
    const pts = [pt(1, [['concentrate', ['MID_LF0'], 262, true], ['spread', ['MID_LF0', 'MID_LF1'], 233, true]]),
      pt(1.4, [['concentrate', ['MID_LF1'], 464, true], ['concentrate', ['MID_LF0'], 496, true], ['spread', ['MID_LF0', 'MID_LF1'], 400, false], ['spread', ['MID_LF0', 'MID_LF1', 'MID_HF'], 409, true]])]
    const m = strategyMatrix(pts)
    expect(m.cols.map((c) => c.label)).toEqual(['LF0 집중', 'LF1 집중', 'LF0 + LF1', 'LF0 + LF1 + HF'])
    expect(m.rows[0].cells[1]).toBeNull()
    expect(m.cols[m.rows[0].best!].label).toBe('LF0 + LF1')
    expect(m.cols[m.rows[1].best!].label).toBe('LF0 + LF1 + HF') // infeasible 400 is not the minimum
    expect(spreadVsConcentrate(pts[1]).concentrate?.clusters).toEqual(['MID_LF1'])
  })
})

describe('sweepStageTip', () => {
  it('shows the RT-chain-aware verdict slack, falling back to the SW room of older responses', () => {
    const chain = sweepStageTip({ stage: 'nrt', sw_ms: 14, room_ms: 20, slack_ms: 6, chain_slack_ms: -1, ok: true })
    expect(chain.v).toBe('-1.00 ms (RT chain · SW room 6.00)')
    expect(chain.tone).toBe('bad')
    const old = sweepStageTip({ stage: 'post', sw_ms: 4, room_ms: 6, slack_ms: 2, ok: true })
    expect(old.k).toBe('POST 여유')
    expect(old.v).toBe('2.00 ms')
    expect(old.tone).toBeUndefined()
  })
})
