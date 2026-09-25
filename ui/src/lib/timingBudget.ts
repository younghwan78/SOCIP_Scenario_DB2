// Stage timing budget: API types + pure helpers used by the Timing Budget pages.
// Backend: POST /timing-budget/variant, /timing-budget/fleet (src/scenario_db/sim/timing_budget.py).
import { API_BASE, ApiError } from './api'

export type StageId = 'rt' | 'nrt' | 'post' | 'output'
export type Statistic = 'min' | 'mean' | 'max'
export type EisMode = 'auto' | 'on' | 'off'

export interface SwItem { task: string; kind: 'sw' | 'ip_overhead'; runtime_ms: number; latency_ms: number; source: string; critical?: boolean }
export interface StageRow {
  id: StageId; name: string; nodes: string[]; sw_items: SwItem[]
  sw_ms: number; budget_ms: number; hw_ms: number; overhead_ms: number; margin: number; feasible: boolean; fill_pct: number
}
export interface IpRow {
  node: string; hw_name: string; stage: StageId; dvfs_group: string | null; cores: number; shared_streams: number
  rule_clock_mhz: number | null; required_clock_mhz: number; set_clock_mhz: number; dvfs_level: number | null; voltage_mv: number
  rule_dvfs_level?: number | null; dvfs_table?: boolean
  hw_ms: number | null; power_mw: number; feasible: boolean; infeasible_reason: string | null; clock_reason: string | null
}
export interface IntervalSeries { node: string | null; values: number[]; max_ms: number | null; min_ms: number | null; ok: boolean | null }
export interface TimelineRow { node: string; type: string; frame: number; start_ms: number; end_ms: number; stage: StageId }
export interface PowerSplit {
  total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; bw_hw_mw: number; bw_sw_mw: number
  share_pct: { cpu: number; hw: number; bw: number }
  hw_by_ip: Record<string, number>; cpu_by_task: Record<string, number>; cpu_busy_ms: number
  cpu_model: { cluster: number; freq_mhz: number; volt_v: number; source: string }; zero_power_ips: string[]
}
export interface BwSplit { total_mbs: number; hw_mbs: number; sw_mbs: number; hw_by_ip: Record<string, number>; sw_by_task: Record<string, number>; share_pct: { hw: number; sw: number } }
export interface Verdict { status: 'ok' | 'clock_up' | 'fail'; reasons: string[]; nrt_clock_factor: number | null }
export interface WhatIfRow {
  statistic: Statistic; eis: boolean; scale: number; verdict: Verdict
  stages: Record<StageId, { sw_ms: number; budget_ms: number; hw_ms: number; feasible: boolean }>
  nrt_driver: string | null; nrt_clock_mhz: number | null; nrt_rule_clock_mhz: number | null; post_clock_mhz: number | null
  interval_ok: boolean
}
export interface TimingReport {
  scenario_id: string; variant_id: string; fps: number; period_ms: number; statistic: Statistic
  eis: { on: boolean; auto: boolean; mode: EisMode; stabilization: unknown }
  mfc_dual: Record<string, number>; growth: { runtime_scale: number; latency_scale: number }
  dvfs: { tables: string[]; applied: boolean; table_ref?: string | null }
  stages: StageRow[]; ips: IpRow[]
  intervals: { target_ms: number; tolerance: number; preview: IntervalSeries; video: IntervalSeries; ok: boolean }
  latency: { preview_ms: number | null; video_ms: number | null; preview_frames: number | null; video_frames: number | null }
  power: PowerSplit; bw: BwSplit; verdict: Verdict; timeline: TimelineRow[]; warnings: string[]; whatif?: WhatIfRow[]
}
export interface FleetRow {
  variant_id: string; fps: number; period_ms: number; statistic: Statistic; eis_on: boolean; stabilization: unknown; mfc_dual: boolean
  stages: Record<StageId, { sw_ms: number; budget_ms: number; hw_ms: number; feasible: boolean }>
  clocks: Record<StageId, { ip: string | null; rule_mhz: number | null; set_mhz: number | null; level: number | null }>
  intervals: { ok: boolean; preview_max_ms: number | null; video_max_ms: number | null }
  latency: TimingReport['latency']
  power: { total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; share_pct: { cpu: number; hw: number; bw: number } }
  bw: { total_mbs: number; hw_mbs: number; sw_mbs: number }
  verdict: Verdict
}
export interface TimingOptions { statistic: Statistic; eis: EisMode; runtime_scale: number; include_whatif?: boolean }

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** fetch with retry on 429: the API admits only N concurrent simulations per worker (non-blocking). */
export async function fetchAdmitted(url: string, init: RequestInit, retries = 6): Promise<Response> {
  for (let i = 0; ; i++) {
    const res = await fetch(url, init)
    if (res.status !== 429 || i >= retries) return res
    const after = Number(res.headers?.get?.('Retry-After') ?? 1)
    await sleep(Math.min(4000, (Number.isFinite(after) && after > 0 ? after * 1000 : 1000) * (0.5 + 0.25 * i) + Math.random() * 200))
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchAdmitted(`${API_BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!res.ok) {
    let detail = ''
    try { const j = await res.json() as { detail?: unknown }; detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j) } catch { /* not json */ }
    throw new ApiError(`${res.status} ${res.statusText} — ${path}${detail ? ` · ${detail}` : ''}`, res.status)
  }
  return res.json() as Promise<T>
}

export const timingApi = {
  variant: (scenarioId: string, variantId: string, options: TimingOptions) =>
    postJson<{ report: TimingReport; dvfs_table_ref: string | null }>('/timing-budget/variant', { scenario_id: scenarioId, variant_id: variantId, options }),
  fleet: (scenarioId: string, options: Omit<TimingOptions, 'include_whatif'>) =>
    postJson<{ rows: FleetRow[]; errors: { variant_id: string; error: string }[]; dvfs_table_ref: string | null }>('/timing-budget/fleet', { scenario_id: scenarioId, options }),
}

// ---------------------------------------------------------------- helpers
export const STAGE_COLOR: Record<StageId, string> = { rt: '#2F6F68', nrt: '#C2410C', post: '#EA8A4E', output: '#4C5E8C' }
export const SW_COLOR = '#B7791F'
export const LAT_COLOR = '#D6CFC2'
export const OVH_COLOR = '#8B5E34'

export interface Segment { key: string; label: string; ms: number; color: string; text: string; tip: string }

/** One stage's slot as ordered segments (latency → SW → overhead → HW), all in ms of the frame period. */
export function stageSegments(stage: StageRow): Segment[] {
  const segs: Segment[] = []
  const critical = stage.sw_items.filter((i) => i.critical !== false)
  if (stage.id === 'rt') {
    segs.push({ key: 'hw', label: 'RT HW', ms: stage.hw_ms, color: STAGE_COLOR.rt, text: '#FFFFFF', tip: `RT HW ${stage.hw_ms.toFixed(2)} ms (25% rule budget ${stage.budget_ms.toFixed(2)})` })
    return segs
  }
  for (const i of critical) {
    if (i.kind === 'ip_overhead') { segs.push({ key: `ovh:${i.task}`, label: `${i.task} drv`, ms: i.runtime_ms, color: OVH_COLOR, text: '#FFFFFF', tip: `${i.task} driver setup/IRQ ${i.runtime_ms.toFixed(2)} ms` }); continue }
    if (i.latency_ms > 0) segs.push({ key: `lat:${i.task}`, label: 'lat', ms: i.latency_ms, color: LAT_COLOR, text: '#3B3F4A', tip: `${i.task} latency ${i.latency_ms.toFixed(2)} ms` })
    segs.push({ key: `sw:${i.task}`, label: i.task, ms: i.runtime_ms, color: SW_COLOR, text: '#FFFFFF', tip: `${i.task} runtime ${i.runtime_ms.toFixed(2)} ms (${i.source})` })
  }
  if (stage.hw_ms > 0) segs.push({ key: 'hw', label: `${stage.name.split(' ')[0]} HW`, ms: stage.hw_ms, color: STAGE_COLOR[stage.id], text: '#FFFFFF', tip: `HW ${stage.hw_ms.toFixed(2)} ms · budget ${stage.budget_ms.toFixed(2)} ms` })
  return segs
}

export function verdictChip(v: Verdict['status']): { label: string; cls: string } {
  if (v === 'ok') return { label: 'OK', cls: 'v-ok' }
  if (v === 'clock_up') return { label: 'Clock ↑', cls: 'v-warn' }
  return { label: 'Fail', cls: 'v-fail' }
}

/** NRT clock factor vs the 25% rule for a fleet row (null when unknown). */
export function nrtFactor(row: FleetRow): number | null {
  const c = row.clocks.nrt
  return c.rule_mhz && c.set_mhz ? c.set_mhz / c.rule_mhz : null
}

/** Frame-to-frame interval check with the report tolerance. */
export function intervalOk(values: number[], target: number, tol: number): boolean {
  return values.every((v) => Math.abs(v - target) <= target * tol)
}

export function fmt(v: number | null | undefined, d = 1): string {
  return v === null || v === undefined || Number.isNaN(v) ? '—' : v.toFixed(d)
}

/** Nice axis max for bar charts. */
export function niceMax(v: number): number {
  if (v <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(v))
  const n = v / p
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p
}

/** '342 (Lv2) → 400 MHz (Lv4)'; a DVFS group without a table reads 'Lv —' with the reason. */
export function clockText(ip: Pick<IpRow, 'rule_clock_mhz' | 'set_clock_mhz' | 'dvfs_level' | 'rule_dvfs_level' | 'dvfs_table' | 'dvfs_group'>): string {
  const lv = (l: number | null | undefined) => (l === null || l === undefined ? 'Lv —' : `Lv${l}`)
  const noTable = ip.dvfs_table === false
  const rule = ip.rule_clock_mhz === null ? '—' : noTable ? fmt(ip.rule_clock_mhz, 0) : `${fmt(ip.rule_clock_mhz, 0)} (${lv(ip.rule_dvfs_level)})`
  return `${rule} → ${fmt(ip.set_clock_mhz, 0)} MHz (${noTable ? `Lv — · ${ip.dvfs_group ?? '?'} 표 없음` : lv(ip.dvfs_level)})`
}
