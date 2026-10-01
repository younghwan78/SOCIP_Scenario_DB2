import { describe, expect, it } from 'vitest'
import { cpuSource, cpuTier, mifSummary, partColor, powerModelParts, sortClusters } from './powerModel'
import { caseCount, caseParts, type CpuCase } from './cpu'

const pb = {
  cpu: { source: 'pmu_profile', total_mw: 80, by_cluster: { MID_HF: 48, DSU: 18, MID_LF: 14 }, dsu: { name: 'DSU' } },
  ip: { total_mw: 300, clock_overhead_mw: 20, leakage_mw: 30 },
  memory: { total_mw: 120, mif: { mif_mhz: 1539, base_mw: 50, other_masters_mw: 10, reason: 'qos_lock', utilization: 0.42 } },
}

describe('powerModelParts', () => {
  it('splits CPU clusters, IP work/leak/clock and memory traffic/base/other', () => {
    const parts = powerModelParts(pb)
    const m = Object.fromEntries(parts.map((p) => [p.key, p.mw]))
    expect(m).toEqual({
      'cpu.MID_LF': 14, 'cpu.MID_HF': 48, 'cpu.dsu': 18,
      'ip.work': 250, 'ip.leak': 30, 'ip.clock': 20,
      'mem.traffic': 60, 'mem.base': 50, 'mem.other': 10,
    })
    const sum = parts.reduce((s, p) => s + p.mw, 0)
    expect(sum).toBeCloseTo(80 + 300 + 120)
  })
  it('handles legacy breakdowns (no cpu, no mif)', () => {
    const parts = powerModelParts({ ip: { total_mw: 10 }, memory: { total_mw: 5 } })
    expect(parts.map((p) => p.key)).toEqual(['ip.work', 'mem.traffic'])
    expect(powerModelParts(null)).toEqual([])
  })
  it('summaries and colours', () => {
    expect(mifSummary(pb)).toBe('MIF 1539 MHz (QoS lock · 42%)')
    expect(mifSummary({})).toBeNull()
    expect(cpuSource(pb)).toBe('CPU: 실측 profile')
    expect(powerModelParts(pb).filter((p) => p.family === 'cpu').map((p) => p.key)).toEqual(['cpu.dsu', 'cpu.MID_LF', 'cpu.MID_HF'])
  })
  it('CPU order DSU < MID_LF < MID_HF < BIG_LF < BIG with separate DSU/MID/BIG colour sets', () => {
    expect(sortClusters(['BIG', 'MID_HF', 'BIG_LF', 'DSU', 'MID_LF'])).toEqual(['DSU', 'MID_LF', 'MID_HF', 'BIG_LF', 'BIG'])
    expect(sortClusters(['MID_HF1', 'BIG', 'MID_HF0', 'BIG_LF'])).toEqual(['MID_HF0', 'MID_HF1', 'BIG_LF', 'BIG'])
    expect(['cpu.dsu', 'cpu.MID_LF0', 'cpu.BIG_LF'].map(cpuTier)).toEqual(['dsu', 'mid', 'big'])
    const order = ['cpu.dsu', 'cpu.MID_LF0', 'cpu.MID_LF1', 'cpu.MID_HF', 'cpu.BIG_LF', 'cpu.BIG']
    const colours = order.map((k) => partColor(k, order))
    expect(new Set(colours).size).toBe(order.length)                     // all distinguishable
    const ipMem = ['ip.work', 'ip.leak', 'ip.clock', 'mem.traffic', 'mem.base', 'mem.other'].map((k) => partColor(k, []))
    expect(colours.some((c) => ipMem.includes(c))).toBe(false)
  })
})

describe('cpu what-if helpers', () => {
  it('caseParts maps clusters + DSU; caseCount multiplies choices', () => {
    const c: CpuCase = {
      placement: { eis: 'MID_HF' }, feasible: true, min_slack_ms: 1, slack_ms: {}, cpu_bw_mbs: 0, total_mw: 30,
      clusters: { MID_HF: { mhz: 1200, util: 0.3, dynamic_mw: 15, static_mw: 5, total_mw: 20 } as CpuCase['clusters'][string] },
      dsu: { active_ratio: 0.5, dynamic_mw: 8, static_mw: 2, total_mw: 10 },
    }
    expect(caseParts(c).map((p) => [p.key, p.mw])).toEqual([['cpu.dsu', 10], ['cpu.MID_HF', 20]])
    expect(caseCount({ eis: ['A', 'B'], post: ['A', 'B', 'C'], x: [] })).toBe(6)
  })
})
