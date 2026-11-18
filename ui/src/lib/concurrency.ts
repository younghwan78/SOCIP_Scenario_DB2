// S-06: concurrent scenarios, static composition (POST /timing-budget/concurrent, src/scenario_db/sim/concurrency.py).
import { postJson } from './api'
import type { TimingOptions } from './timingBudget'

export interface ConcurrentMemberRow {
  member: string; scenario_id: string; variant_id: string; verdict: string | null; fps: number
  total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; bw_mbs: number; cpu_load: number; dvfs_raise_mw: number
}
export interface SharedDomain {
  group: string; clock_mhz: number; mv: number; members: string[]; delta_mw: number
  raised: { member: string; node: string; own_mhz: number; own_mv: number; delta_mw: number }[]
}
export interface ConcurrentResult {
  members: ConcurrentMemberRow[]
  power: { total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; dvfs_raise_mw: number; sum_of_members_mw: number }
  bw: { total_mbs: number; peak_upper_mbs: number }
  cpu: { load_core_eq: number }
  shared_domains: SharedDomain[]
  shared_nodes: { node: string; members: string[]; mw: number }[]
  verdict: { status: 'ok' | 'fail'; failing_members: string[]; notes: string[] }
  limits: string[]
  dvfs_table_refs: string[]
}

export const concurrencyApi = {
  compose: (members: { scenario_id: string; variant_id: string }[], options: Partial<TimingOptions>, configProfileRef?: string | null) =>
    postJson<ConcurrentResult>('/timing-budget/concurrent',
      { members, options: { ...options, include_whatif: false }, config_profile_ref: configProfileRef ?? undefined }),
}

/** "uc-vid-youtube-e2600/yt-1080p30" -> "vid-youtube / yt-1080p30" (the uc- prefix and the SoC suffix dropped). */
export const memberLabel = (m: string) => m.replace(/^uc-/, '').replace(/-e\d{4}\//, ' / ')
