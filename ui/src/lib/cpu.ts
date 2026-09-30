// CPU placement / frequency what-if (POST /cpu/whatif) and its pickers (GET /cpu/inputs).
import { getJson, postJson } from './api'

export interface CpuInputs {
  topologies: { id: string; version: number; soc_ref: string; clusters: string[] }[]
  profiles: { id: string; scenario_ref: string | null; variant_ref: string | null; project_ref: string | null }[]
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

export const cpuApi = {
  inputs: () => getJson<CpuInputs>('/cpu/inputs'),
  whatif: (req: CpuWhatIfRequest) => postJson<{ result: CpuWhatIf }>('/cpu/whatif', req).then((r) => r.result),
}
