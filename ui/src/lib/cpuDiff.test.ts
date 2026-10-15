import { expect, it } from 'vitest'
import { cpuDiff, cpuDiffHeadline, cpuSideOf } from './cpuDiff'

// P = k·a/T rows: k = mW at 100 % util, a = active ms/frame, T = period
const row = (task: string, cluster: string, k: number, a: number, T: number, extra = {}) =>
  ({ task, cluster, active_ms: a, util: a / T, power_mw: (k * a) / T, ...extra })
const side = (rows: ReturnType<typeof row>[]) => {
  const pb = { cpu: { total_mw: rows.reduce((s, r) => s + r.power_mw, 0), by_cluster: {} } }
  return cpuSideOf({ cpu_breakdown: rows, power_breakdown: pb }, pb)!
}

it('splits each task change exactly into SW load, period (fps) and placement/coefficient', () => {
  const base = side([row('eis', 'MID_LF0', 300, 4, 33.33, { wall_ms: 4 }), row('post_irta', 'MID_LF0', 300, 3, 33.33)])
  // eis runs 5 ms instead of 4 at 60 fps; post_irta moves to a cluster with a higher coefficient
  const cand = side([row('eis', 'MID_LF0', 300, 5, 16.67, { wall_ms: 5 }), row('post_irta', 'MID_HF', 450, 3, 16.67), row('mpeg_writer', 'MID_LF0', 300, 0.4, 16.67)])
  const d = cpuDiff(base, cand)
  expect(d.detailed).toBe(true)
  const sum = d.effects.load + d.effects.period + d.effects.coef + d.effects.unsplit + d.effects.added + d.effects.removed + d.effects.other
  expect(sum).toBeCloseTo(d.delta, 6)
  expect(Math.abs(d.effects.other)).toBeLessThan(1e-9)            // nothing left unexplained
  const eis = d.tasks.find((t) => t.task === 'eis')!
  expect(eis.effects.load).toBeCloseTo((300 * 1) / 33.33, 6)       // +1 ms at the reference period
  expect(eis.effects.coef).toBeCloseTo(0, 9)
  expect(eis.reasons.join(' ')).toContain('SW 실행 4.00→5.00 ms')
  const irta = d.tasks.find((t) => t.task === 'post_irta')!
  expect(irta.reasons.join(' ')).toContain('cluster MID_LF0→MID_HF')
  expect(irta.effects.coef).toBeGreaterThan(0)
  expect(d.tasks.find((t) => t.task === 'mpeg_writer')!.kind).toBe('added')
  expect(cpuDiffHeadline(d)).toMatch(/^\+\d+\.\d mW = /)
})

it('falls back to per-task totals when only the power breakdown is stored', () => {
  const base = cpuSideOf(null, { cpu: { total_mw: 50, by_cluster: { MID_LF0: 50 }, by_task: { eis: 30, post_irta: 20 } } })!
  const cand = cpuSideOf(null, { cpu: { total_mw: 62, by_cluster: { MID_LF0: 40, MID_HF: 22 }, by_task: { eis: 40, post_irta: 22 } } })!
  const d = cpuDiff(base, cand)
  expect(d.detailed).toBe(false)
  expect(d.effects.unsplit).toBeCloseTo(12)
  expect(d.clusters.find((c) => c.name === 'MID_HF')!.delta).toBeCloseTo(22)
  expect(cpuSideOf(null, { cpu: { total_mw: 0, by_cluster: {} } })).toBeNull()
})

it('never combines stored totals with task rows from an unrelated preview', () => {
  const preview = { cpu: { total_mw: 90, by_task: { eis: 90 } } }
  const stored = { cpu: { total_mw: 40, by_task: { irta: 40 } } }
  const result = { power_breakdown: preview, cpu_breakdown: [row('eis', 'MID_LF0', 300, 10, 33.33)] }
  const selected = cpuSideOf(result, stored)!
  expect(selected.rows).toBeNull()
  expect(selected.byTask).toEqual({ irta: 40 })
  expect(selected.total).toBe(40)
  expect(cpuSideOf(result, preview)!.rows).toHaveLength(1)
})

it('keeps unknown causes unsplit and preserves an explicit zero total', () => {
  const base = side([row('eis', 'MID_LF0', 300, 4, 33.33, { active_ms: undefined, util: undefined })])
  const cand = side([row('eis', 'MID_LF0', 400, 4, 33.33, { active_ms: undefined, util: undefined })])
  const d = cpuDiff(base, cand)
  expect(d.effects.load).toBe(0)
  expect(d.effects.unsplit).toBeCloseTo(d.delta)
  expect(d.tasks[0].reasons.join(' ')).toContain('원인 미분해')
  expect(cpuSideOf(null, { cpu: { total_mw: 0, by_task: { stale: 20 } } })!.total).toBe(0)
})
