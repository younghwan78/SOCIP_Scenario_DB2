// CPU placement / frequency what-if (POST /cpu/whatif) and its pickers (GET /cpu/inputs).
import { getJson } from './api'
import { postAdmitted } from './timingBudget'

export interface CpuInputs {
  topologies: { id: string; version: number; soc_ref: string; clusters: string[] }[]
  profiles: { id: string; scenario_ref: string | null; variant_ref: string | null; project_ref: string | null; tasks?: { task: string; cluster: string; threads?: number | null }[] }[]
}

type Topology = CpuInputs['topologies'][number]
type Profile = CpuInputs['profiles'][number]
/** Share of the profile's measured clusters that exist in the topology (1 = all tasks map). */
export function clusterCover(t: Topology, p: Profile | undefined): number {
  const need = [...new Set((p?.tasks ?? []).map((x) => x.cluster).filter(Boolean))]
  if (!need.length) return 0
  return need.filter((c) => t.clusters.includes(c)).length / need.length
}
/** Topologies matching the profile's clusters first, then newest version. */
export function rankTopologies(list: Topology[], p: Profile | undefined): Topology[] {
  return [...list].sort((a, b) => clusterCover(b, p) - clusterCover(a, p) || b.version - a.version)
}

export interface CpuCluster {
  mhz: number; mv: number; util: number; busy_ms: number; dynamic_mw: number; static_mw: number; total_mw: number
  tasks_ms: Record<string, number>; feasible?: boolean
}

export interface CpuCase {
  rank?: number; placement: Record<string, string>; clusters: Record<string, CpuCluster>
  dsu: { active_ratio: number; dynamic_mw: number; static_mw: number; total_mw: number } | null
  total_mw: number; delta_mw?: number; feasible: boolean; min_slack_ms: number | null; slack_ms: Record<string, number>; cpu_bw_mbs: number
}

export interface CpuWhatIf {
  target: { name: string; cores: number; core_type?: string }[]
  measured_mw: number | null; fps: number; tasks: string[]; base: CpuCase; cases: CpuCase[]; case_count: number
  pareto_ranks: number[]; warnings: string[]
}

export interface CpuWhatIfRequest {
  cpu_profile_ref: string; power_params_ref: string; base_power_params_ref?: string; fps: number
  default_growth: number; growth: Record<string, number>; candidates: Record<string, string[]>; budgets_ms: Record<string, number>
  util_cap: number; power_gating_eff: number; cpu_bw_scale: number
}

/** "eis=MID_LF,MID_HF; post_irta=MID_HF" -> {eis: [...], post_irta: [...]} */
export function parseListMap(text: string): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  for (const part of text.split(/[;\n]/)) {
    const [k, v] = part.split('=')
    if (k?.trim() && v?.trim()) out[k.trim()] = v.split(',').map((s) => s.trim()).filter(Boolean)
  }
  return out
}

/** "eis=6; post_irta=8.5" -> {eis: 6, post_irta: 8.5} (non-numbers dropped) */
export function parseNumberMap(text: string): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [k, v] of Object.entries(parseListMap(text))) {
    const n = Number(v[0])
    if (Number.isFinite(n)) out[k] = n
  }
  return out
}

// ---------------------------------------------------------------- EAS sweep (POST /cpu/sweep)
export type Knob = 'pin' | 'upto' | 'uclamp_max' | 'uclamp_min'
export interface KnobOption { kind: 'eas' | 'measured' | Knob; clusters?: string[]; excluded?: string[]; value?: number }

export interface SweepCpu { cpu: number | string; util: number; busy_ms: number; overloaded: boolean; threads: string[] }
export interface SweepCluster extends CpuCluster {
  capacity: number; sched_mhz: number; boosted_by: string[]; cpus: SweepCpu[]
}
export interface SweepCase {
  rank?: number; placement: Record<string, string[]>; clusters: Record<string, SweepCluster>
  dsu: { mhz?: number; active_ratio: number; dynamic_mw: number; static_mw: number; total_mw: number } | null
  total_mw: number; delta_mw?: number; feasible: boolean; task_ms: Record<string, number>; slack_ms: Record<string, number>
  min_slack_ms: number | null; flags: Record<string, string[] | boolean>; cpu_bw_mbs: number
  knobs: Record<string, KnobOption>; moved?: string[]
  equivalents?: { knobs: Record<string, KnobOption>; total_mw: number; placement: Record<string, string[]> }[]
}
export interface SweepCell { t_fmax_ms: number; util_fmax: number; fits: boolean; meets: boolean; in_sweep: boolean }
export interface SweepRangeTask {
  task: string; threads: { name: string; t_fmax_ms: number }[]; thread_source: 'measured' | 'given' | 'single'
  measured: string[]; policy: Record<string, unknown>; budget_ms: number | null; growth: number
  cells: Record<string, SweepCell>; options: KnobOption[]
}
export interface SweepRangeCluster {
  name: string; core_type: string | null; cores: number; cpus: number[]; capacity: number; ipc_rel: number
  opp_min_mhz: number; opp_max_mhz: number; opp_count: number
}
export interface CpuSweep {
  scheduler: { model: string; freq_margin: number; fits_margin: number; util_model: string; pelt_halflife_ms: number
    deadline_boost: boolean; energy_includes_static: boolean; capacity: Record<string, number>; power_gating_eff: number
    from_params: boolean; source: string | null }
  fps: number; period_ms: number
  range: { clusters: SweepRangeCluster[]; tasks: SweepRangeTask[]; knobs: string[]; space: number; evaluated: number; unique: number; method: 'exhaustive' | 'beam' }
  measured_mw: number | null
  calibration: Record<string, { eas_mhz: number; eas_util: number; measured_mean_mhz?: number; measured_active?: number }>
  reference_kind: 'measured' | 'eas'; reference: SweepCase; eas_default: SweepCase; measured_placement: SweepCase
  cases: SweepCase[]; better_count: number; equal_mw: number; others: SweepCase[]; other_count: number; tasks: string[]; warnings: string[]
}
export interface CpuSweepRequest {
  cpu_profile_ref: string; power_params_ref: string; base_power_params_ref?: string; fps: number
  default_growth: number; growth: Record<string, number>; budgets_ms: Record<string, number>; threads: Record<string, number>
  sweep_clusters: Record<string, string[]>; knobs: Knob[]; uclamp_max_levels: number[]; uclamp_min_levels: number[]
  reference: 'measured' | 'eas'; power_gating_eff: number; cpu_bw_scale: number
  freq_margin?: number; fits_margin?: number; util_model?: 'util_est' | 'pelt_avg'; pelt_halflife_ms?: number
  deadline_boost?: boolean; energy_includes_static?: boolean
  /** better cases returned (power ascending); server default 60 */
  top?: number
}

export const cpuApi = {
  inputs: () => getJson<CpuInputs>('/cpu/inputs'),
  // simulation admission slots (429 when busy) are shared with exploration / timing: retry like those clients
  whatif: (req: CpuWhatIfRequest) => postAdmitted<{ result: CpuWhatIf }>('/cpu/whatif', req).then((r) => r.result),
  sweep: (req: CpuSweepRequest) => postAdmitted<{ result: CpuSweep }>('/cpu/sweep', req).then((r) => r.result),
}

/** "256, 512" -> [256, 512] (0..1024 integers) */
export function parseLevels(text: string): number[] {
  return text.split(/[,\s]+/).map(Number).filter((v) => Number.isInteger(v) && v >= 0 && v <= 1024)
}

/** Human label of one sweep knob (what to change on the device). */
export function knobLabel(task: string, o: KnobOption): string {
  switch (o.kind) {
    case 'pin': return `${task} → ${o.clusters?.join('/')} 고정`
    case 'upto': return `${task} ≤ ${o.clusters?.[o.clusters.length - 1]}${o.excluded?.length ? ` (${o.excluded.join('·')} 제외)` : ''}`
    case 'uclamp_max': return `${task} uclamp.max ${o.value}`
    case 'uclamp_min': return `${task} uclamp.min ${o.value}`
    case 'measured': return `${task} 측정 위치`
    default: return `${task} EAS`
  }
}

/** How the knob is realised on an Android device. */
export function knobHow(o: KnobOption): string {
  switch (o.kind) {
    case 'pin': return 'cpuset / sched_setaffinity'
    case 'upto': return 'cpuset 제한 (또는 uclamp.max)'
    case 'uclamp_max': case 'uclamp_min': return 'sched_setattr uclamp · HAL perf hint'
    case 'measured': return '현재 상태'
    default: return 'EAS 자유 배치'
  }
}

/** Placement change vs a reference case: "eis MID_HF→MID_LF0". */
export function movedLabel(c: SweepCase, ref: SweepCase): string[] {
  return Object.entries(c.placement)
    .filter(([t, cl]) => (ref.placement[t] ?? []).join('/') !== cl.join('/'))
    .map(([t, cl]) => `${t} ${(ref.placement[t] ?? []).join('/') || '—'}→${cl.join('/')}`)
}

import { compareCpu, type PowerPart } from './powerModel'

/** A what-if case as power parts: one per cluster (dynamic + static) plus the DSU. */
export function caseParts(c: CpuCase | SweepCase): PowerPart[] {
  const parts: PowerPart[] = Object.entries(c.clusters).map(([name, cl]) => ({
    key: `cpu.${name}`, label: name, family: 'cpu' as const, mw: cl.total_mw,
    note: `${cl.mhz} MHz · util ${(cl.util * 100).toFixed(1)}% · dyn ${cl.dynamic_mw.toFixed(1)} / static ${cl.static_mw.toFixed(1)} mW`,
  }))
  if (c.dsu) parts.push({ key: 'cpu.dsu', label: 'DSU', family: 'cpu', mw: c.dsu.total_mw, note: `active ${(c.dsu.active_ratio * 100).toFixed(0)}%` })
  return parts.sort((a, b) => compareCpu(a.key, b.key))
}

/** Number of placements the checked matrix produces. */
export function caseCount(candidates: Record<string, string[]>): number {
  return Object.values(candidates).reduce((n, v) => n * Math.max(1, v.length), 1)
}

/** Cluster frequency changes vs a reference: "MID_HF 1200→600". */
export function freqChanges(c: SweepCase, ref: SweepCase): string[] {
  return Object.entries(c.clusters)
    .filter(([n, x]) => ref.clusters[n] && ref.clusters[n].mhz !== x.mhz && (x.busy_ms > 0 || ref.clusters[n].busy_ms > 0))
    .map(([n, x]) => `${n} ${ref.clusters[n].mhz}→${x.mhz}`)
}
