import { expect, it } from 'vitest'
import { breakEven, stageDomainsOf, whatIfDomains, type IpRow, type WhatIfRow } from '../src/lib/timingBudget'

// cam-rec-r1-uhd30-vdis shape: NRT = CAM (held by RT at 266) + INTCAM (SW-budget driven, 133 -> 266 at x1.4)
const row = (scale: number, intcam: number, req: number): WhatIfRow => ({
  statistic: 'max', eis: true, scale, verdict: { status: intcam > 133 ? 'clock_up' : 'ok', reasons: [], nrt_clock_factor: intcam / 133 },
  stages: { rt: { sw_ms: 0, budget_ms: 25, hw_ms: 10.18, feasible: true }, nrt: { sw_ms: 11, budget_ms: 22, hw_ms: 18.5, feasible: true },
    post: { sw_ms: 6, budget_ms: 27, hw_ms: 8, feasible: true }, output: { sw_ms: 2, budget_ms: 25, hw_ms: 8, feasible: true } },
  nrt_driver: 'mtnr', nrt_clock_mhz: intcam, nrt_rule_clock_mhz: 133, post_clock_mhz: 266, interval_ok: true,
  domains: { nrt: [
    { domain: 'CAM', ip: 'yuvp', rule_mhz: 266, required_mhz: req, set_mhz: 266, level: 6 },
    { domain: 'INTCAM', ip: 'mtnr', rule_mhz: 133, required_mhz: req, set_mhz: intcam, level: intcam > 133 ? 4 : 5 },
  ] },
})
const rows = [row(1.0, 133, 110.6), row(1.2, 133, 121.7), row(1.3, 133, 128.2), row(1.4, 266, 135.2), row(1.5, 266, 139.6)]

it('what-if domains: the domain SW growth moves comes first; CAM (fixed by RT) after', () => {
  expect(whatIfDomains(rows)).toEqual(['INTCAM', 'CAM'])
})

it('break-even: first growth that needs the next DVFS level, per domain', () => {
  expect(breakEven(rows, 'INTCAM', 'max', true)).toEqual({ scale: 1.4, from: 133, to: 266 })
  expect(breakEven(rows, 'CAM', 'max', true)).toBeNull()
  expect(breakEven(rows, 'INTCAM', 'mean', true)).toBeNull()
})

it('stage domains derived from IP rows (older API): one per DVFS domain, SW-stage IP never the driver', () => {
  const ip = (node: string, group: string, set: number, req: number, hw: number, reason: string | null = null): IpRow => ({
    node, hw_name: node, stage: 'nrt', dvfs_group: group, cores: 1, shared_streams: 1, rule_clock_mhz: set, required_clock_mhz: req,
    set_clock_mhz: set, dvfs_level: 4, voltage_mv: 700, hw_ms: hw, power_mw: 1, feasible: true, infeasible_reason: null, clock_reason: reason })
  const ds = stageDomainsOf({ ips: [ip('lme', 'CAM', 400, 342.3, 0.5, 'included_stage_budget(pre_me_rta, 4ms; lower bound)'), ip('yuvp', 'CAM', 400, 342.3, 6.1),
    ip('mtnr', 'INTCAM', 133, 110.6, 18.5)] }, 'nrt')
  expect(ds.map((d) => [d.domain, d.ip, d.set_mhz])).toEqual([['CAM', 'yuvp', 400], ['INTCAM', 'mtnr', 133]])
})
