import { describe, expect, it } from 'vitest'
import { frameHue, frameSliceStyle, sliceCat } from '../src/lib/timeline'
import { marginOf, marginOpts, pct0 } from '../src/lib/timingBudget'
import { domainGroups } from '../src/components/TimingCharts'
import { delta } from '../src/components/CompareSummary'
import { threadLabel } from '../src/components/CpuHelp'
import { bufferState } from '../src/components/ArchCharts'
import type { IpRow } from '../src/lib/timingBudget'

describe('frame × category timeline colors', () => {
  it('same frame shares a hue, categories differ in shade / pattern', () => {
    const rt = frameSliceStyle(1, 'RT'), nrt = frameSliceStyle(1, 'NRT'), m2m = frameSliceStyle(1, 'M2M'), sw = frameSliceStyle(1, 'SW')
    for (const st of [rt, nrt, m2m, sw]) expect(st.fill.startsWith(`hsl(${frameHue(1)} `)).toBe(true)
    expect(new Set([rt.fill, nrt.fill, m2m.fill, sw.fill]).size).toBe(4)
    expect([m2m.pattern, sw.pattern, rt.pattern]).toEqual(['m2m', 'sw', null])
    expect(frameHue(0)).not.toBe(frameHue(1))
    expect(sliceCat('CODEC')).toBe('OUT'); expect(sliceCat('CONCURRENT')).toBe('SW')
  })
})

describe('SW margin param', () => {
  it('defaults to 25 % and only sends overrides', () => {
    expect(marginOf(undefined)).toBe(0.25); expect(marginOf('20')).toBe(0.2); expect(marginOf('99')).toBe(0.25)
    expect(marginOpts(0.25)).toEqual({}); expect(marginOpts(0.3)).toEqual({ rt_margin: 0.3, output_margin: 0.3 })
    expect(pct0(0.15)).toBe('15%')
  })
})

describe('clock chart DVFS grouping', () => {
  const ip = (node: string, stage: IpRow['stage'], group: string, level: number, req: number): IpRow => ({
    node, hw_name: node, stage, dvfs_group: group, cores: 1, shared_streams: 1, rule_clock_mhz: req, required_clock_mhz: req, set_clock_mhz: req,
    dvfs_level: level, voltage_mv: 700, hw_ms: 1, power_mw: 1, feasible: true, infeasible_reason: null, clock_reason: null })
  it('groups by domain, highest level IP drives the domain', () => {
    const g = domainGroups([ip('mcsc', 'nrt', 'CAM', 3, 300), ip('byrp', 'rt', 'CAM', 4, 400), ip('mtnr', 'nrt', 'INTCAM', 5, 111)])
    expect(g.map((x) => x.domain)).toEqual(['CAM', 'INTCAM'])
    expect(g[0].rows.map((r) => r.node)).toEqual(['byrp', 'mcsc'])
    expect([g[0].level, g[0].driver.node]).toEqual([4, 'byrp'])
  })
})

describe('compare delta tone', () => {
  it('lower power is good, higher fps is good, ±1 % is same', () => {
    expect(delta(90, 100)?.tone).toBe('good'); expect(delta(110, 100)?.tone).toBe('bad')
    expect(delta(100.5, 100)?.tone).toBe('same'); expect(delta(60, 30, false)?.tone).toBe('good')
    expect(delta(null, 100)).toBeNull()
  })
})

describe('labels', () => {
  it('numeric thread part is a TID', () => {
    expect(threadLabel('post_crta#2098')).toBe('post_crta · tid 2098'); expect(threadLabel('eis')).toBe('eis')
  })
  it('buffer state separates unsupported DMA from the max_buffers cap', () => {
    const b = { buffer: 'X', format: '', family: 'YUV', nodes: [], support: 'unknown', selectable: false }
    expect(bufferState({ ...b, skip_reason: 'compression support not declared: gdc_o' }, []).key).toBe('unsupported')
    expect(bufferState({ ...b, skip_reason: 'outside top 8 savings (max_buffers)' }, []).key).toBe('cap')
    expect(bufferState({ ...b, explored: true }, ['X']).key).toBe('on')
  })
})
