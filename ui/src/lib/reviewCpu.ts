// CPU-11: CPU what-if results recorded for the project review (server re-runs the sweep and keeps a summary).
import { getJson, postJson } from './api'
import type { CpuRebalanceRequest } from './rebalance'
import type { OppEvent } from './growthSweep'

export interface CpuSnapshotSummary {
  tolerance: number | null; binding: 'opp' | 'timing' | null; timing_at: number | null; opp_step: OppEvent | null; opp_step_best_mw: number | null
  growth_range: [number, number] | null
  points: { growth: number; ref_mw: number | null; best_mw: number | null; ref_feasible: boolean | null; bw_mw: number | null }[]
  best_at_start: { total_mw: number | null; moved: string[]; delta_mw: number | null }
  profile_origin?: string
  /** cpu-sweep/2: sweep revision · Timing Budget SW statistic · RT placement the numbers rest on */
  basis?: { rev?: string; timing_statistic?: string; timing_coupling?: string; rt_placement?: string | null }
  opp_steps?: OppEvent[]; timing_fail_at?: number | null
}
export interface CpuSnapshot {
  id: string; project_ref: string; scenario_id: string; variant_id: string; profile_ref: string; power_params_ref: string
  base_power_params_ref: string | null; status: 'active' | 'superseded' | 'withdrawn'; note: string | null
  created_by: string | null; created_at: string | null; summary: CpuSnapshotSummary
  /** false = recorded by an older sweep calculation: re-record (갱신) before the next report */
  calc_rev?: string | null; calc_current?: boolean
}

export const cpuSnapshotApi = {
  list: (projectRef: string) => getJson<CpuSnapshot[]>('/review/cpu-snapshots', { project_ref: projectRef }, false),
  create: (projectRef: string, request: CpuRebalanceRequest & { growths: number[] }, note?: string) =>
    postJson<CpuSnapshot>('/review/cpu-snapshots', { project_ref: projectRef, request, note }),
  withdraw: (id: string) => postJson<CpuSnapshot>(`/review/cpu-snapshots/${encodeURIComponent(id)}/withdraw`, {}),
}
