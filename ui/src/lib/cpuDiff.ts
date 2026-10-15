// CPU predicted-power difference vs the ★ reference, attributed to causes.
//
// Every modelled CPU task row satisfies  P = k · a / T
//   a = CPU-active ms per frame (SW runtime × invocations × active ratio, or PMU busy time)
//   T = frame period (1000 / fps)            -> T = a / util
//   k = mW at 100 % of one core on that cluster at its OPP (coefficient · f · V²)  -> k = P / util
// so the change of each task splits exactly (sequential attribution, sums to ΔP):
//   SW 부하   k_b · (a_c − a_b) / T_b
//   주기(fps) k_b · a_c · (1/T_c − 1/T_b)
//   배치·계수 (k_c − k_b) · a_c / T_c      (cluster move, or frequency / voltage / params change)
// Tasks only on one side are "추가 / 제거"; cluster terms without tasks (DSU, static) are "기타".
import type { Dict } from './api'

export interface CpuTaskRow {
  task: string; cluster: string; power_mw: number; active_ms?: number; util?: number
  wall_ms?: number; invocations_per_frame?: number; cpu_active_ratio?: number; cycles_per_frame?: number; source?: string
}
export interface CpuSide { total: number; rows: CpuTaskRow[] | null; byTask: Record<string, number>; byCluster: Record<string, number>; source: string | null }
export type CpuEffect = 'load' | 'period' | 'coef' | 'unsplit' | 'added' | 'removed' | 'other'
export interface CpuTaskDiff {
  task: string; kind: 'both' | 'added' | 'removed'; base: number; cand: number; delta: number
  effects: Partial<Record<CpuEffect, number>>; reasons: string[]; clusterBase?: string; clusterCand?: string
}
export interface CpuDiff {
  base: number; cand: number; delta: number; detailed: boolean
  effects: Record<CpuEffect, number>
  tasks: CpuTaskDiff[]
  clusters: { name: string; base: number; cand: number; delta: number }[]
}
export const EFFECT_LABEL: Record<CpuEffect, string> = {
  load: 'SW 부하 (실행 시간·호출 수)', period: '주기 (fps)', coef: 'cluster 배치 · 주파수/전압 계수', unsplit: 'task 전력 변화 (원인 미분해)', added: 'task 추가', removed: 'task 제거', other: '기타 (DSU · static · 미분해)',
}

const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
const obj = (v: unknown): Dict => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Dict) : {})

/** CPU side of one compare item: task rows from a simulation result when present, else the power_breakdown totals. */
export function cpuSideOf(result: Dict | null | undefined, pb: Dict | null | undefined): CpuSide | null {
  const cpu = obj(pb?.cpu ?? obj(result?.power_breakdown).cpu)
  const raw = Array.isArray(result?.cpu_breakdown) ? (result!.cpu_breakdown as Dict[]) : null
  const rows = raw?.filter((r) => typeof r.task === 'string' && typeof r.power_mw === 'number')
    .map((r): CpuTaskRow => ({ task: String(r.task), cluster: String(r.cluster ?? ''), power_mw: num(r.power_mw), active_ms: num(r.active_ms), util: num(r.util),
      wall_ms: typeof r.wall_ms === 'number' ? r.wall_ms : undefined, invocations_per_frame: typeof r.invocations_per_frame === 'number' ? r.invocations_per_frame : undefined,
      cpu_active_ratio: typeof r.cpu_active_ratio === 'number' ? r.cpu_active_ratio : undefined, cycles_per_frame: typeof r.cycles_per_frame === 'number' ? r.cycles_per_frame : undefined,
      source: typeof r.source === 'string' ? r.source : undefined })) ?? null
  const byTask: Record<string, number> = {}
  if (rows?.length) for (const r of rows) byTask[r.task] = (byTask[r.task] ?? 0) + r.power_mw
  else for (const [k, v] of Object.entries(obj(cpu.by_task))) byTask[k] = num(v)
  const byCluster: Record<string, number> = Object.fromEntries(Object.entries(obj(cpu.by_cluster)).map(([k, v]) => [k, num(v)]))
  const total = num(cpu.total_mw) || Object.values(byCluster).reduce((a, b) => a + b, 0) || Object.values(byTask).reduce((a, b) => a + b, 0)
  if (!total && !rows?.length && !Object.keys(byTask).length) return null
  return { total, rows: rows?.length ? rows : null, byTask, byCluster, source: typeof cpu.source === 'string' ? cpu.source : rows?.[0]?.source ?? null }
}

interface Agg { power: number; active: number; util: number; clusters: Set<string>; wall?: number; inv?: number; ratio?: number }
function aggregate(rows: CpuTaskRow[]): Map<string, Agg> {
  const out = new Map<string, Agg>()
  for (const r of rows) {
    const a = out.get(r.task) ?? { power: 0, active: 0, util: 0, clusters: new Set<string>() }
    a.power += r.power_mw; a.active += r.active_ms ?? 0; a.util += r.util ?? 0; a.clusters.add(r.cluster)
    if (r.wall_ms !== undefined) a.wall = (a.wall ?? 0) + r.wall_ms
    if (r.invocations_per_frame !== undefined) a.inv = r.invocations_per_frame
    if (r.cpu_active_ratio !== undefined) a.ratio = r.cpu_active_ratio
    out.set(r.task, a)
  }
  return out
}
const f = (v: number, d = 2) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(d))
const clusterText = (s: Set<string>) => [...s].sort().join('+')

export function cpuDiff(base: CpuSide, cand: CpuSide): CpuDiff {
  const effects: Record<CpuEffect, number> = { load: 0, period: 0, coef: 0, unsplit: 0, added: 0, removed: 0, other: 0 }
  const tasks: CpuTaskDiff[] = []
  const detailed = !!(base.rows && cand.rows)
  if (detailed) {
    const A = aggregate(base.rows!), B = aggregate(cand.rows!)
    for (const task of new Set([...A.keys(), ...B.keys()])) {
      const b = A.get(task), c = B.get(task)
      if (b && !c) { effects.removed -= b.power; tasks.push({ task, kind: 'removed', base: b.power, cand: 0, delta: -b.power, effects: { removed: -b.power }, reasons: [`★에만 있음 (${clusterText(b.clusters)})`], clusterBase: clusterText(b.clusters) }); continue }
      if (!b && c) { effects.added += c.power; tasks.push({ task, kind: 'added', base: 0, cand: c.power, delta: c.power, effects: { added: c.power }, reasons: [`비교 항목에만 있음 (${clusterText(c.clusters)})`], clusterCand: clusterText(c.clusters) }); continue }
      const bb = b!, cc = c!
      const delta = cc.power - bb.power
      const e: Partial<Record<CpuEffect, number>> = {}
      if (bb.util > 0 && cc.util > 0 && bb.active > 0 && cc.active > 0) {
        const kb = bb.power / bb.util, kc = cc.power / cc.util
        const Tb = bb.active / bb.util, Tc = cc.active / cc.util
        e.load = (kb * (cc.active - bb.active)) / Tb
        e.period = kb * cc.active * (1 / Tc - 1 / Tb)
        e.coef = ((kc - kb) * cc.active) / Tc
      } else e.load = delta
      for (const [k, v] of Object.entries(e)) effects[k as CpuEffect] += v ?? 0
      const reasons: string[] = []
      if (bb.wall !== undefined && cc.wall !== undefined && Math.abs(cc.wall - bb.wall) > 1e-3) reasons.push(`SW 실행 ${f(bb.wall)}→${f(cc.wall)} ms`)
      if (bb.inv !== undefined && cc.inv !== undefined && bb.inv !== cc.inv) reasons.push(`호출 ${f(bb.inv, 1)}→${f(cc.inv, 1)}회/frame`)
      if (bb.ratio !== undefined && cc.ratio !== undefined && Math.abs(bb.ratio - cc.ratio) > 1e-3) reasons.push(`CPU active ${(bb.ratio * 100).toFixed(0)}→${(cc.ratio * 100).toFixed(0)}%`)
      if (Math.abs(cc.active - bb.active) > 1e-3 && !reasons.length) reasons.push(`CPU active ${f(bb.active)}→${f(cc.active)} ms/frame`)
      if (bb.util > 0 && cc.util > 0) { const Tb = bb.active / bb.util, Tc = cc.active / cc.util; if (Math.abs(Tc - Tb) > 1e-3) reasons.push(`주기 ${f(Tb)}→${f(Tc)} ms`) }
      const cb = clusterText(bb.clusters), cl = clusterText(cc.clusters)
      if (cb !== cl) reasons.push(`cluster ${cb}→${cl}`)
      else if (Math.abs(e.coef ?? 0) > 0.05) reasons.push(`${cl} 계수 변화 (주파수·전압·power params)`)
      tasks.push({ task, kind: 'both', base: bb.power, cand: cc.power, delta, effects: e, reasons, clusterBase: cb, clusterCand: cl })
    }
  } else {
    for (const task of new Set([...Object.keys(base.byTask), ...Object.keys(cand.byTask)])) {
      const b = base.byTask[task] ?? 0, c = cand.byTask[task] ?? 0
      const kind = !(task in base.byTask) ? 'added' : !(task in cand.byTask) ? 'removed' : 'both'
      tasks.push({ task, kind, base: b, cand: c, delta: c - b, effects: kind === 'both' ? { unsplit: c - b } : kind === 'added' ? { added: c } : { removed: -b },
        reasons: kind === 'both' ? [] : [kind === 'added' ? '비교 항목에만 있음' : '★에만 있음'] })
      if (kind === 'added') effects.added += c
      else if (kind === 'removed') effects.removed -= b
      else effects.unsplit += c - b
    }
  }
  const delta = cand.total - base.total
  const explained = effects.load + effects.period + effects.coef + effects.unsplit + effects.added + effects.removed
  effects.other = delta - explained
  tasks.sort((p, q) => Math.abs(q.delta) - Math.abs(p.delta))
  const clusters = [...new Set([...Object.keys(base.byCluster), ...Object.keys(cand.byCluster)])].sort()
    .map((name) => ({ name, base: base.byCluster[name] ?? 0, cand: cand.byCluster[name] ?? 0, delta: (cand.byCluster[name] ?? 0) - (base.byCluster[name] ?? 0) }))
  return { base: base.total, cand: cand.total, delta, detailed, effects, tasks, clusters }
}

/** One-line answer: the biggest causes, e.g. "+23.4 mW = SW 부하 +18.0 · 주기 (fps) +4.1 · …". */
export function cpuDiffHeadline(d: CpuDiff): string {
  const parts = (Object.entries(d.effects) as [CpuEffect, number][]).filter(([, v]) => Math.abs(v) >= 0.05)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).map(([k, v]) => `${EFFECT_LABEL[k]} ${v >= 0 ? '+' : ''}${v.toFixed(1)}`)
  return `${d.delta >= 0 ? '+' : ''}${d.delta.toFixed(1)} mW${parts.length ? ` = ${parts.join(' · ')}` : ''}`
}
