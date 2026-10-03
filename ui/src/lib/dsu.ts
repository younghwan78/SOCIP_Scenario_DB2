// DSU <-> cluster clock coupling for the CPU what-if (mirror of sim/cpu_dsu.py).
// The DSU vote does not change cluster OPPs or placement (EAS compares cluster energy only), so a new vote table
// is evaluated here from the sweep response — no new simulation — and the cases are re-ranked.
import type { CpuSweep, SweepCase } from './cpu'

export type DsuMode = 'auto' | 'vote' | 'proportional' | 'measured' | 'fixed'
export type VoteTable = Record<string, [number, number][]>
export interface DsuOpp { mhz: number; mv: number; mw_per_core: number | null }
export interface DsuParams {
  opps: DsuOpp[]; leak_mw_per_core_at_ref: number; leak_ref_mv: number; leak_exponent: number
  fallback_mv: number; power_gating_eff: number
  clusters: { name: string; core_type: string | null; opps_mhz: number[] }[]
}
export interface DsuModelInfo { mode: Exclude<DsuMode, 'auto'>; requested: DsuMode; source: string | null; vote?: VoteTable; fixed_mhz?: number }
/** client-side experiment (mode never 'auto') */
export interface DsuPolicy { mode: Exclude<DsuMode, 'auto'>; vote?: VoteTable; fixed_mhz?: number }

const snap = (p: DsuParams, mhz: number) => (p.opps.find((o) => o.mhz >= mhz - 1e-9) ?? p.opps[p.opps.length - 1]).mhz
const oppFor = (p: DsuParams, mhz: number) => p.opps.find((o) => o.mhz >= mhz - 1e-9) ?? p.opps[p.opps.length - 1]

/** vote entry of a cluster: exact name, then case-insensitive name, then core type (as the server). */
export function voteEntry(table: VoteTable, name: string, coreType: string | null): [number, number][] | undefined {
  if (table[name]) return table[name]
  const k = Object.keys(table)
  const byName = k.find((x) => x.toLowerCase() === name.toLowerCase())
  if (byName) return table[byName]
  const byType = coreType ? k.find((x) => x.toLowerCase() === coreType.toLowerCase()) : undefined
  return byType ? table[byType] : undefined
}

export function clusterVote(table: VoteTable, name: string, coreType: string | null, mhz: number): number | null {
  const pts = voteEntry(table, name, coreType)
  if (!pts?.length) return null
  return (pts.find(([f]) => f >= mhz - 1e-9) ?? pts[pts.length - 1])[1]
}

export function residency(policy: DsuPolicy, p: DsuParams, busy: Record<string, number>, measured?: Record<string, number> | null): Record<number, number> {
  if (policy.mode === 'measured') return Object.fromEntries(Object.entries(measured ?? {}).map(([f, v]) => [Number(f), v]))
  if (policy.mode === 'fixed') return { [snap(p, policy.fixed_mhz ?? 0)]: 1 }
  const meta = new Map(p.clusters.map((c) => [c.name, c]))
  if (policy.mode === 'vote') {
    const votes = Object.entries(busy).map(([n, f]) => clusterVote(policy.vote ?? {}, n, meta.get(n)?.core_type ?? null, f)).filter((v): v is number => v !== null)
    return { [votes.length ? snap(p, Math.max(...votes)) : p.opps[0].mhz]: 1 }
  }
  const rel = Math.max(0, ...Object.entries(busy).map(([n, f]) => { const o = meta.get(n)?.opps_mhz ?? []; return o.length ? f / o[o.length - 1] : 0 }))
  return { [snap(p, rel * p.opps[p.opps.length - 1].mhz)]: 1 }
}

export function dsuPower(p: DsuParams, res: Record<number, number>, active: number) {
  const entries = Object.entries(res).map(([f, s]) => [Number(f), s] as const)
  const total = entries.reduce((a, [, s]) => a + s, 0) || 1
  const leak = (mv: number) => (p.leak_mw_per_core_at_ref > 0 && p.leak_ref_mv > 0 ? p.leak_mw_per_core_at_ref * (mv / p.leak_ref_mv) ** p.leak_exponent : 0)
  let dyn = 0, lk = 0, mhz = 0
  for (const [f, s] of entries) {
    const o = oppFor(p, f)
    dyn += (s / total) * (o.mw_per_core ?? 0) * (o.mhz > 0 ? f / o.mhz : 1) * active
    lk += (s / total) * leak(o.mv ?? p.fallback_mv)
    mhz += (f * s) / total
  }
  const stat = lk * (active + (1 - active) * (1 - p.power_gating_eff))
  return { mhz: Math.round(mhz * 10) / 10, active_ratio: active, dynamic_mw: dyn, static_mw: stat, total_mw: dyn + stat }
}

export function recomputeCase(c: SweepCase, policy: DsuPolicy, p: DsuParams, measured?: Record<string, number> | null): SweepCase {
  if (!c.dsu) return c
  const busy = Object.fromEntries(Object.entries(c.clusters).filter(([, r]) => r.busy_ms > 0).map(([n, r]) => [n, r.mhz]))
  const d = dsuPower(p, residency(policy, p, busy, measured), c.dsu.active_ratio)
  return { ...c, dsu: d, total_mw: c.total_mw - c.dsu.total_mw + d.total_mw }
}

/** Re-evaluate every returned case under ``policy`` and re-split / re-rank like the server (within the returned cases). */
export function applyDsu(r: CpuSweep, policy: DsuPolicy | null): CpuSweep {
  const p = r.dsu_params
  if (!policy || !p) return r
  const re = (c: SweepCase) => recomputeCase(c, policy, p, r.dsu_measured)
  const reference = re(r.reference)
  const withDelta = (c: SweepCase): SweepCase => ({ ...c, delta_mw: c.total_mw - reference.total_mw })
  const pool = [...r.cases, ...r.others].map(re).map(withDelta)
  const better = pool.filter((c) => c.feasible && ((c.delta_mw ?? 0) < -1e-6 || !reference.feasible))
    .sort((a, b) => a.total_mw - b.total_mw || Object.keys(a.knobs).length - Object.keys(b.knobs).length)
    .map((c, i) => ({ ...c, rank: i + 1 }))
  const others = pool.filter((c) => !better.some((b) => b.knobs === c.knobs && b.placement === c.placement))
    .sort((a, b) => Number(!a.feasible) - Number(!b.feasible) || a.total_mw - b.total_mw).map((c) => ({ ...c, rank: undefined }))
  return {
    ...r, reference: { ...reference, delta_mw: 0 }, eas_default: withDelta(re(r.eas_default)), measured_placement: withDelta(re(r.measured_placement)),
    cases: better, better_count: better.length, others, other_count: others.length,
    dsu_model: { mode: policy.mode, requested: policy.mode, source: 'experiment', vote: policy.vote, fixed_mhz: policy.fixed_mhz },
  }
}

/** vote table that reproduces the proportional fallback (a starting point for editing). */
export function proportionalVote(p: DsuParams): VoteTable {
  const top = p.opps[p.opps.length - 1].mhz
  return Object.fromEntries(p.clusters.filter((c) => c.opps_mhz.length).map((c) => {
    const fmax = c.opps_mhz[c.opps_mhz.length - 1]
    return [c.name, c.opps_mhz.map((f) => [f, snap(p, (f / fmax) * top)] as [number, number])]
  }))
}

/** per-cluster table (one row per cluster, one point per cluster OPP) from any table keyed by name or core type. */
export function expandVote(table: VoteTable, p: DsuParams): VoteTable {
  return Object.fromEntries(p.clusters.filter((c) => c.opps_mhz.length).map((c) => [c.name,
    c.opps_mhz.map((f) => [f, clusterVote(table, c.name, c.core_type, f) ?? p.opps[0].mhz] as [number, number])]))
}

/** every vote moved ``steps`` DSU OPPs (corner of an assumed table); keeps the table non-decreasing. */
export function shiftVote(table: VoteTable, p: DsuParams, steps: number): VoteTable {
  const fs = p.opps.map((o) => o.mhz)
  const mv = (d: number) => { const i = fs.findIndex((f) => f >= d - 1e-9); return fs[Math.min(fs.length - 1, Math.max(0, (i < 0 ? fs.length - 1 : i) + steps))] }
  return Object.fromEntries(Object.entries(table).map(([k, pts]) => [k, pts.map(([f, d]) => [f, mv(d)] as [number, number])]))
}

/** force a table non-decreasing (an edited cell lifts the following ones). */
export function monotone(pts: [number, number][]): [number, number][] {
  let m = 0
  return pts.map(([f, d]) => { m = Math.max(m, d); return [f, m] })
}

export function voteYaml(table: VoteTable, source = 'estimate'): string {
  return [`vote_source: ${source}`, 'vote:', ...Object.entries(table).map(([k, pts]) =>
    `- cluster: ${k}\n  points: [${pts.map(([f, d]) => `[${f}, ${d}]`).join(', ')}]`)].join('\n')
}

export interface PolicySummary { refMw: number; bestMw: number | null; deltaMw: number | null; bestDsuMhz: number | null; refDsuMhz: number | null; best: SweepCase | null }
export function summarize(r: CpuSweep): PolicySummary {
  const best = r.cases[0] ?? null
  return { refMw: r.reference.total_mw, bestMw: best?.total_mw ?? null, deltaMw: best ? best.total_mw - r.reference.total_mw : null,
    bestDsuMhz: best?.dsu?.mhz ?? null, refDsuMhz: r.reference.dsu?.mhz ?? null, best }
}
