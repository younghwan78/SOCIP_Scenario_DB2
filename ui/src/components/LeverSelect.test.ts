import { describe, expect, it } from 'vitest'
import { lookupPoint, milestoneSelection } from './LeverSelect'
import { caseGroups, type LeverAnalysis, type LeverPoint, type VariantResult } from '../lib/archExplore'

const pt = (option_keys: string[], comp: Record<string, string>, total: number): LeverPoint =>
  ({ options: option_keys, option_keys, comp, iq: 'neutral', total_mw: total, bw_mbs: 0, cpu_mw: 0, hw_mw: 0, bw_mw: 0 })
const points = [pt([], {}, 100), pt([], { L0: 'COMP_YUV_LOSSLESS' }, 90), pt(['knob:l0=skip'], {}, 70), pt(['knob:l0=skip'], { L1: 'COMP_YUV_LOSSY' }, 65)]

describe('lever selector', () => {
  it('finds the evaluated point and drops compression of buffers the options remove', () => {
    expect(lookupPoint(points, { options: [], comp: { L0: 'COMP_YUV_LOSSLESS' } }).point?.total_mw).toBe(90)
    const r = lookupPoint(points, { options: ['knob:l0=skip'], comp: { L0: 'COMP_YUV_LOSSLESS' } })
    expect(r.point?.total_mw).toBe(70)
    expect(r.moot).toEqual(['L0'])
  })
  it('maps milestone option labels back to item keys', () => {
    const la = { status: 'ok', levers: [{ key: 'knob:l0=skip', kind: 'option', label: 'L0 skip', iq: 'eval', confidence: '', alone: null, in_context: null, overlap: false }],
      milestones: { eval: { total_mw: 70, bw_mbs: 0, delta_mw: -30, delta_pct: -30, options: ['L0 skip'], compression: {} } } } as LeverAnalysis
    expect(milestoneSelection(la, 'eval')).toEqual({ options: ['knob:l0=skip'], comp: {} })
  })
})

describe('case groups', () => {
  it('splits design points by IQ cost and hides DVFS raise unless asked', () => {
    const base = { key: 'b', statistic: 'max', runtime_scale: 1, compression: [], dvfs: { CAM: 7 }, dvfs_raise: 0, total_mw: 100, cpu_mw: 0, hw_mw: 0, bw_mw: 0, bw_mbs: 0, lossy: false, assumed_ratio: false, verdict: 'ok', eligible: true }
    const v = {
      baseline: base, recommended: { ...base, key: 'r', total_mw: 80, lossy: true, compression: ['L0'] },
      alternatives: [{ ...base, key: 'up', total_mw: 105, dvfs_raise: 1 }], pareto: [],
      design_points: [{ key: 'b', comp: {}, total_mw: 100, cpu_mw: 0, hw_mw: 0, bw_mw: 0, bw_mbs: 0, lossy: false, assumed: false },
        { key: 'll', comp: { L0: 'COMP_YUV_LOSSLESS' }, total_mw: 90, cpu_mw: 0, hw_mw: 0, bw_mw: 0, bw_mbs: 0, lossy: false, assumed: false },
        { key: 'r', comp: { L0: 'COMP_YUV_LOSSY' }, total_mw: 80, cpu_mw: 0, hw_mw: 0, bw_mw: 0, bw_mbs: 0, lossy: true, assumed: false }],
    } as unknown as VariantResult
    const g = caseGroups(v, false)
    expect(g.keep.map((c) => c.key)).toEqual(['ll', 'b'])
    expect(g.trade.map((c) => c.key)).toEqual(['r'])
    expect(caseGroups(v, true).keep.map((c) => c.key)).toEqual(['ll', 'b', 'up'])
  })
})
