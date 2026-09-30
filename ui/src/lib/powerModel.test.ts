import { describe, expect, it } from 'vitest'
import { cpuSource, mifSummary, partColor, powerModelParts } from './powerModel'
import { caseCount, caseParts, type CpuCase } from './cpu'

const pb = {
  cpu: { source: 'pmu_profile', total_mw: 80, by_cluster: { MID_LF: 14, MID_HF: 48, DSU: 18 }, dsu: { name: 'DSU' } },
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
    expect(partColor('cpu.dsu', [])).toBe('#8FA3B8')
    expect(partColor('cpu.B', ['cpu.A', 'cpu.B'])).not.toBe(partColor('cpu.A', ['cpu.A', 'cpu.B']))
  })
})

describe('cpu what-if helpers', () => {
  it('caseParts maps clusters + DSU; caseCount multiplies choices', () => {
    const c: CpuCase = {
      placement: { eis: 'MID_HF' }, feasible: true, min_slack_ms: 1, slack_ms: {}, cpu_bw_mbs: 0, total_mw: 30,
      clusters: { MID_HF: { mhz: 1200, util: 0.3, dynamic_mw: 15, static_mw: 5, total_mw: 20 } as CpuCase['clusters'][string] },
      dsu: { active_ratio: 0.5, dynamic_mw: 8, static_mw: 2, total_mw: 10 },
    }
    expect(caseParts(c).map((p) => [p.key, p.mw])).toEqual([['cpu.MID_HF', 20], ['cpu.dsu', 10]])
    expect(caseCount({ eis: ['A', 'B'], post: ['A', 'B', 'C'], x: [] })).toBe(6)
  })
})
