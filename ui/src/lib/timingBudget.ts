// Stage timing budget: API types + pure helpers used by the Timing Budget pages.
// Backend: POST /timing-budget/variant, /timing-budget/fleet (src/scenario_db/sim/timing_budget.py).
import { API_BASE, ApiError } from './api'
import type { VariantFailure } from '../components/VariantFailures'

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
  /** IP's own need before DVFS-domain sharing, the constraint that set it, and why the set clock is higher */
  own_required_mhz?: number; basis?: ClockBasisKind; set_reason?: SetReason; domain_leader?: string | null
  next_level_mhz?: number | null; sensor_readout_ms?: number | null
  /** OTF-linked group (any DVFS domain): hw_ms is the group's time; standalone_hw_ms = this IP alone at its clock */
  otf_group?: string | null; standalone_hw_ms?: number | null
}
export type ClockBasisKind = 'budget' | 'rule' | 'sensor_readout' | 'mipi_ingress' | 'vvalid_stream' | 'otf_align' | 'stage_budget' | 'manual' | string
export type SetReason = 'exact' | 'dvfs_step' | 'dvfs_floor' | 'domain'
/** One DVFS domain of a stage (NRT = CAM + INTCAM …). */
export interface StageDomain {
  domain: string; ip: string; nodes: string[]; rule_mhz: number | null; required_mhz: number; set_mhz: number
  level: number | null; rule_level: number | null; next_mhz: number | null; headroom_pct: number | null; hw_ms: number
  basis: ClockBasisKind | null; set_reason: SetReason | null; domain_leader: string | null
}
export type DomainClock = Pick<StageDomain, 'domain' | 'ip' | 'rule_mhz' | 'required_mhz' | 'set_mhz' | 'level'>
export interface IntervalSeries { node: string | null; values: number[]; max_ms: number | null; min_ms: number | null; ok: boolean | null }
export interface TimelineRow { node: string; type: string; frame: number; start_ms: number; end_ms: number; stage: StageId }
export interface PowerSplit {
  total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; bw_hw_mw: number; bw_sw_mw: number
  share_pct: { cpu: number; hw: number; bw: number }
  hw_by_ip: Record<string, number>; cpu_by_task: Record<string, number>; cpu_busy_ms: number
  cpu_model: { cluster: number; freq_mhz: number; volt_v: number; source: string }; zero_power_ips: string[]
  /** cpu_model=profile: measured CPU profile replayed with SW growth (absent = flat assumption) */
  cpu_profile?: CpuProfileTerm
  cpu_mw_flat?: number; bw_sw_mw_model?: number
}
export interface CpuProfileTerm {
  kind: 'profile' | 'flat'; note?: string; profile_ref?: string | null; growth?: number
  clusters?: Record<string, { mhz: number; total_mw: number; busy_ms: number }>; dsu_mhz?: number | null; dsu_mw?: number
  feasible?: boolean; cpu_mw_flat?: number; bw_source?: 'model' | 'measured'; bw_mw_per_mbs?: number
}
export type CpuModel = 'flat' | 'profile'
/** Short tile note for the CPU power of a timing report. */
export function cpuTileNote(p: PowerSplit): string {
  const c = p.cpu_profile
  if (c?.kind === 'profile') {
    const ops = Object.entries(c.clusters ?? {}).filter(([, v]) => v.busy_ms > 0).map(([k, v]) => `${k.replace(/^MID_/, '')} ${v.mhz}`).join(' · ')
    return `측정 profile ×${c.growth} · ${ops}${c.dsu_mhz ? ` · DSU ${c.dsu_mhz}` : ''} · 가정 모델 ${fmt(c.cpu_mw_flat ?? null, 0)} mW`
  }
  return `${fmt(p.cpu_busy_ms, 1)} ms/frame · CL${p.cpu_model.cluster} ${p.cpu_model.freq_mhz} MHz ${p.cpu_model.volt_v} V${c?.note ? ` · ${c.note}` : ''}`
}
export interface BwSplit { total_mbs: number; hw_mbs: number; sw_mbs: number; hw_by_ip: Record<string, number>; sw_by_task: Record<string, number>; share_pct: { hw: number; sw: number } }
export interface Verdict { status: 'ok' | 'clock_up' | 'fail'; reasons: string[]; notes?: string[]; nrt_clock_factor: number | null }
export interface WhatIfRow {
  statistic: Statistic; eis: boolean; scale: number; verdict: Verdict
  stages: Record<StageId, { sw_ms: number; budget_ms: number; hw_ms: number; feasible: boolean }>
  nrt_driver: string | null; nrt_clock_mhz: number | null; nrt_rule_clock_mhz: number | null; post_clock_mhz: number | null
  interval_ok: boolean
  /** per stage, one clock per DVFS domain (absent before API stage_domains) */
  domains?: Partial<Record<StageId, DomainClock[]>>
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
  stage_domains?: Partial<Record<StageId, StageDomain[]>>
  /** SW margin rule applied to RT/Output (and the NRT/Post rule reference); absent before API sw_margin */
  sw_margin?: { rt: number; output: number }
}
export interface FleetRow {
  variant_id: string; fps: number; period_ms: number; statistic: Statistic; eis_on: boolean; stabilization: unknown; mfc_dual: boolean
  stages: Record<StageId, { sw_ms: number; budget_ms: number; hw_ms: number; feasible: boolean }>
  clocks: Record<StageId, { ip: string | null; rule_mhz: number | null; set_mhz: number | null; level: number | null; domain?: string | null; domains?: DomainClock[] }>
  intervals: { ok: boolean; preview_max_ms: number | null; video_max_ms: number | null }
  latency: TimingReport['latency']
  power: { total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; share_pct: { cpu: number; hw: number; bw: number } }
  bw: { total_mbs: number; hw_mbs: number; sw_mbs: number }
  verdict: Verdict
}
export interface TimingOptions {
  statistic: Statistic; eis: EisMode; runtime_scale: number; include_whatif?: boolean
  /** CPU term: flat assumption (default) or the variant's measured CPU profile through EAS */
  cpu_model?: CpuModel
  /** SW margin rule (fraction of the frame period reserved for SW); default 0.25 */
  rt_margin?: number; output_margin?: number
  /** frames drawn in the pipeline timeline (API ≤ 32) */
  timeline_frames?: number
}

export const DEFAULT_SW_MARGIN = 0.25
export const SW_MARGINS = [0.15, 0.2, 0.25, 0.3, 0.35]
/** URL param ('margin', percent) → fraction; invalid / missing → 25 %. */
export function marginOf(param: string | undefined): number {
  const v = Number(param)
  return Number.isFinite(v) && v >= 5 && v <= 60 ? v / 100 : DEFAULT_SW_MARGIN
}
export const pct0 = (m: number) => `${Math.round(m * 100)}%`
/** Margin options for API calls: both rule margins follow the one SW margin. */
export const marginOpts = (m: number) => (Math.abs(m - DEFAULT_SW_MARGIN) < 1e-9 ? {} : { rt_margin: m, output_margin: m })

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

/** POST to a simulation endpoint: a 429 (per-process admission slot busy) is retried with backoff. */
export const postAdmitted = postJson

export const timingApi = {
  variant: (scenarioId: string, variantId: string, options: TimingOptions, configProfileRef?: string | null) =>
    postJson<{ report: TimingReport; dvfs_table_ref: string | null; config_profile_ref?: string | null }>('/timing-budget/variant',
      { scenario_id: scenarioId, variant_id: variantId, options, config_profile_ref: configProfileRef ?? undefined }),
  fleet: (scenarioId: string, options: Omit<TimingOptions, 'include_whatif'>, configProfileRef?: string | null) =>
    postJson<{ rows: FleetRow[]; errors: VariantFailure[]; dvfs_table_ref: string | null; config_profile_ref?: string | null }>('/timing-budget/fleet',
      { scenario_id: scenarioId, options, config_profile_ref: configProfileRef ?? undefined }),
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
    segs.push({ key: 'hw', label: 'RT HW', ms: stage.hw_ms, color: STAGE_COLOR.rt, text: '#FFFFFF', tip: `RT HW ${stage.hw_ms.toFixed(2)} ms (sensor readout 종속 · rule budget ${stage.budget_ms.toFixed(2)} ms)` })
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

// ---------------------------------------------------------------- clock basis (what set the clock)
export const BASIS_LABEL: Record<string, string> = {
  budget: 'SW 반영 예산', rule: 'margin rule', sensor_readout: 'sensor readout', vvalid_stream: 'sensor readout',
  mipi_ingress: 'MIPI ingress', otf_align: 'OTF rate 정렬', stage_budget: 'SW stage 포함 (lower bound)', manual: '수동 지정',
}
export const SET_REASON_LABEL: Record<SetReason, string> = {
  exact: '필요값 그대로', dvfs_step: 'DVFS level 올림', dvfs_floor: 'DVFS 최저 level', domain: 'domain 공유',
}
export const basisLabel = (k: string | null | undefined) => (k ? BASIS_LABEL[k] ?? k : '—')

/** 'INTCAM 133 (L5)' */
export function domainClockText(d: Pick<DomainClock, 'domain' | 'set_mhz' | 'level'>): string {
  return `${d.domain} ${fmt(d.set_mhz, 0)}${d.level !== null && d.level !== undefined ? ` (L${d.level})` : ''}`
}

/** Domains of a stage in the what-if grid, most-moving first (the one SW growth pushes). */
export function whatIfDomains(rows: WhatIfRow[], stage: StageId = 'nrt'): string[] {
  const span = new Map<string, number[]>()
  for (const r of rows) for (const d of r.domains?.[stage] ?? []) span.set(d.domain, [...(span.get(d.domain) ?? []), d.set_mhz])
  return [...span.entries()].sort((a, b) => (Math.max(...b[1]) - Math.min(...b[1])) - (Math.max(...a[1]) - Math.min(...a[1])) || a[0].localeCompare(b[0])).map(([d]) => d)
}

export function domainOf(r: WhatIfRow, domain: string, stage: StageId = 'nrt'): DomainClock | undefined {
  return r.domains?.[stage]?.find((d) => d.domain === domain)
}

/** First SW growth where the domain needs a faster DVFS level than at the smallest scale (null = never in range). */
export function breakEven(rows: WhatIfRow[], domain: string, statistic: string, eis: boolean, stage: StageId = 'nrt'): { scale: number; from: number; to: number } | null {
  const pts = rows.filter((r) => r.statistic === statistic && r.eis === eis).sort((a, b) => a.scale - b.scale)
  const first = pts.length ? domainOf(pts[0], domain, stage) : undefined
  if (!first) return null
  for (const r of pts) {
    const d = domainOf(r, domain, stage)
    if (d && d.set_mhz > first.set_mhz + 0.5) return { scale: r.scale, from: first.set_mhz, to: d.set_mhz }
  }
  return null
}

/** Stage DVFS domains from the report; derived from the IP rows for an API without stage_domains. */
export function stageDomainsOf(r: Pick<TimingReport, 'ips' | 'stage_domains'>, stage: StageId): StageDomain[] {
  const given = r.stage_domains?.[stage]
  if (given) return given
  const by = new Map<string, IpRow[]>()
  for (const ip of r.ips.filter((i) => i.stage === stage && i.set_clock_mhz > 0)) by.set(ip.dvfs_group ?? ip.node, [...(by.get(ip.dvfs_group ?? ip.node) ?? []), ip])
  const inSw = (i: IpRow) => i.basis === 'stage_budget' || (i.clock_reason ?? '').startsWith('included_stage_budget')
  return [...by.entries()].map(([domain, members]) => {
    const timed = members.filter((m) => !inSw(m)).length ? members.filter((m) => !inSw(m)) : members
    const need = (m: IpRow) => m.own_required_mhz ?? m.required_clock_mhz
    const d = [...timed].sort((a, b) => need(b) - need(a) || (b.hw_ms ?? 0) - (a.hw_ms ?? 0))[0]
    const req = Math.max(...timed.map(need))
    return { domain, ip: d.node, nodes: members.map((m) => m.node).sort(), rule_mhz: d.rule_clock_mhz, required_mhz: req, set_mhz: d.set_clock_mhz,
      level: d.dvfs_level, rule_level: d.rule_dvfs_level ?? null, next_mhz: d.next_level_mhz ?? null, headroom_pct: req > 0 ? (d.set_clock_mhz / req - 1) * 100 : null,
      hw_ms: Math.max(...timed.map((m) => m.hw_ms ?? 0)), basis: d.basis ?? null, set_reason: d.set_reason ?? null, domain_leader: d.domain_leader ?? null }
  }).sort((a, b) => b.set_mhz - a.set_mhz || a.domain.localeCompare(b.domain))
}

/** IPs that set an OTF group's time (the slowest stream members), by group id. */
export function otfPacers(ips: IpRow[]): Map<string, string[]> {
  const out = new Map<string, string[]>()
  for (const ip of ips) if (ip.otf_group && (ip.standalone_hw_ms === null || ip.standalone_hw_ms === undefined)) out.set(ip.otf_group, [...(out.get(ip.otf_group) ?? []), ip.node])
  return out
}
