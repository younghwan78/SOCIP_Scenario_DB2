import { expect, it } from 'vitest'
import { cpuDiff, cpuDiffHeadline, cpuPickReason, cpuSideOf, pickCpuSide } from './cpuDiff'
import type { SimState } from './simRun'

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

// A finished same-session run, as useSimRuns stores it.
const done = (rows: ReturnType<typeof row>[]): SimState => {
  const pb = { cpu: { total_mw: rows.reduce((s, r) => s + r.power_mw, 0), by_cluster: { MID_LF1: 1 } } }
  return { status: 'done', req: { scenario_id: 's', variant_id: 'v' }, res: { evidence_id: 'e', kpi: {}, result: { power_breakdown: pb, cpu_breakdown: rows } } } as unknown as SimState
}

it('prefers a finished run over stored evidence without CPU (Evidence-first mode regression)', () => {
  const storedNoCpu = { ip: { total_mw: 130 }, cpu: { total_mw: 0, by_cluster: {} } }
  // stored evidence alone: nothing to show, and the reason asks for a run
  const before = pickCpuSide(undefined, storedNoCpu)
  expect(before.side).toBeNull()
  expect(before.state).toBe('none')
  // after the run the card uses its task rows, whatever the stored evidence says
  const after = pickCpuSide(done([row('eis', 'MID_LF1', 300, 3, 33.33)]), storedNoCpu)
  expect(after.source).toBe('sim')
  expect(after.side!.rows).toHaveLength(1)
  // stored evidence that does carry CPU totals is used until a run exists
  const storedCpu = { cpu: { total_mw: 40, by_task: { eis: 40 } } }
  expect(pickCpuSide(undefined, storedCpu).source).toBe('stored')
  expect(pickCpuSide(done([row('eis', 'MID_LF1', 300, 3, 33.33)]), storedCpu).source).toBe('sim')
})

it('says why an item has no CPU side: running, failed run, run without CPU model', () => {
  expect(pickCpuSide({ status: 'running' }, null).state).toBe('running')
  const failed = pickCpuSide({ status: 'error', error: '422 Unprocessable Entity — basis inputs changed' }, null)
  expect(failed.state).toBe('error')
  expect(cpuPickReason(failed)).toContain('basis inputs changed')
  const noModel = pickCpuSide(done([]), null)   // run finished, CPU bucket empty (profile without cpu block)
  expect(noModel.state).toBe('nocpu')
  expect(cpuPickReason(noModel)).toContain('CPU 모델')
  // a failed rerun does not hide stored CPU totals
  expect(pickCpuSide({ status: 'error', error: 'x' }, { cpu: { total_mw: 40, by_task: { eis: 40 } } }).source).toBe('stored')
})
