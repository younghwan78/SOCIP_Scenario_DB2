// Architecture exploration → predictions (current/superseded) → review reports.
// Backend: /arch/exploration/runs, /arch/predictions/*, /arch/reports (src/scenario_db/api/routers/arch_exploration.py)
import { API_BASE, ApiError } from './api'
import { fetchAdmitted, type Statistic } from './timingBudget'

export interface Quant { min: number; p25: number; median: number; p75: number; max: number }
/** Distribution keys always present (engine rev 1+); the BW IP/CPU keys exist from rev 2. */
export type Dist = Record<'total_mw' | 'cpu_mw' | 'hw_mw' | 'bw_mw' | 'bw_mbs', Quant> & Partial<Record<DistKey, Quant>>
export type DistKey = 'total_mw' | 'cpu_mw' | 'hw_mw' | 'bw_mw' | 'bw_ip_mw' | 'bw_cpu_mw' | 'bw_mbs' | 'bw_ip_mbs' | 'bw_cpu_mbs'
export interface Verified { ok: boolean; delta_pct: number; sim_total_mw: number; analytic_total_mw: number; sim_verdict: string }
export interface ExpCase {
  key: string; statistic: Statistic; runtime_scale: number; compression: string[]; dvfs: Record<string, number>; dvfs_raise: number
  total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; bw_mbs: number; lossy: boolean; assumed_ratio: boolean
  // engine rev 2+: BW split into IP BW (HW nodes) and CPU BW (SW tasks)
  bw_ip_mw?: number; bw_cpu_mw?: number; bw_ip_mbs?: number; bw_cpu_mbs?: number
  verdict: string; eligible: boolean; verified?: Verified
}
export interface BufferRow {
  buffer: string; format: string; family: string; nodes: string[]; support: string; selectable: boolean; explored?: boolean
  skip_reason?: string | null; mode?: string; comp_ratio?: number; ratio_source?: string; lossy?: boolean
  raw_mbs?: number; delta_mbs?: number; delta_mw?: number; ports?: string[]
}
export interface DomainOpt { level: number; speed_mhz: number; voltage_mv: number; delta_mw: number; raise: boolean }
export interface DomainRow { domain: string; base_level: number; nodes: string[]; max_required_mhz: number; options: DomainOpt[] }
export interface MarginStage {
  stage: string; slack_ms: number; margin_pct: number; sw_ms: number; hw_ms: number; sw_share_pct: number
  latency_share_pct: number; bottleneck: string | null; bottleneck_ms: number; bottleneck_share_pct: number
}
export interface SwMargin { stages: MarginStage[]; worst: MarginStage | null; growth_tolerance: number | null; growth_tested_max: number | null; stat_spread_ms: number; verdict: string; recommendations: string[] }
export interface SliceRow {
  statistic: Statistic; runtime_scale: number; verdict: { status: string; reasons: string[] }; intervals_ok: boolean
  power: { total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number }; bw: { total_mbs: number }
}
export interface VariantResult {
  scenario_id: string; variant_id: string; fps: number; period_ms: number; eis_on: boolean; mfc_dual: boolean
  spec_ok: boolean; spec_reasons: string[]; counts: { cases: number; eligible: number; sw_slices: number; compression_sets: number; dvfs_sets: number }
  distribution: Dist; baseline: ExpCase; recommended: ExpCase | null; alternatives: ExpCase[]
  slices: SliceRow[]; buffers: BufferRow[]; domains: DomainRow[]
  axis_spread: Record<'sw_statistic' | 'sw_growth' | 'compression' | 'dvfs_headroom', { min: number; max: number; range: number }>
  sw_margin: SwMargin; coverage?: { zero_power_ips: string[]; hw_power_modeled: boolean; cpu_power_modeled: boolean }
  warnings: string[]; dvfs_table_ref?: string | null; input_hash: string
}
export interface RunMeta {
  id: string; title: string; scenario_type: string; project_ref: string | null; soc_ref: string | null; dvfs_table_ref: string | null
  engine_rev: string; created_by: string | null; created_at: string | null
  summary: { variants: number; errors: number; spec_ok: number; cases: number; eligible_cases: number; verified: number; recommended_power_mw: [number, number] | null }
}
export interface RunDetail extends RunMeta { spec: Record<string, unknown>; variants: VariantResult[]; errors: { variant_id: string; error: string }[] }
export interface Power { total_mw: number; cpu_mw: number; hw_mw: number; bw_mw: number; bw_ip_mw?: number; bw_cpu_mw?: number }
export interface BoardRow {
  id: string; scenario_id: string; variant_id: string; status: string; run_id: string; run_title: string | null; run_created_at: string | null
  case_key: string; selection_rule: string; selected_by: string; reason: string | null; created_at: string | null
  fps: number; power: Power; bw_mbs: number; distribution: Dist | null; compression: string[]; dvfs: Record<string, number>
  verdict: string; eligible_cases: number; alternatives: number; verified: Verified | null; statistic: Statistic; runtime_scale: number
  previous: { id: string; total_mw: number; delta_mw: number } | null
}
export interface HistoryRow { id: string; status: string; run_id: string; selection_rule: string; reason: string | null; created_at: string | null; total_mw: number; power: Power; bw_mbs: number }
export interface Factor { category: string; item: string; delta_mw: number; detail: string }
export interface Attribution {
  old_total_mw: number; new_total_mw: number; delta_mw: number; delta_pct: number | null
  components: { cpu_mw: number; hw_mw: number; bw_mw: number; bw_ip_mw?: number; bw_cpu_mw?: number }; by_category: Record<string, number>; factors: Factor[]
  residual_mw: number; context_changes: { item: string; old: unknown; new: unknown }[]
}
export interface ReportMeta {
  id: string; title: string; status: 'draft' | 'published'; target_soc_ref: string | null; project_ref: string | null; scenario_type: string
  run_ids: string[]; dvfs_table_ref: string | null; engine_rev: string; html_sha256: string; generated_by: string | null; generated_at: string | null
  spec_ok: number | null; explored: number | null
}

export interface RunOptions {
  statistics: Statistic[]; runtime_scales: number[]; dvfs_headroom_levels: number
  modes: ('lossy' | 'lossless')[]; max_buffers: number; allow_lossy: boolean; objective_statistic: Statistic; objective_scale: number
}
export const DEFAULT_RUN: RunOptions = {
  statistics: ['mean', 'max'], runtime_scales: [1.0, 1.1, 1.2], dvfs_headroom_levels: 1,
  modes: ['lossy'], max_buffers: 8, allow_lossy: true, objective_statistic: 'max', objective_scale: 1.0,
}

/** Request body for POST /arch/exploration/runs. */
export function runBody(scenarioIds: string[], title: string, scenarioType: string, o: RunOptions) {
  const scales = [...new Set([...o.runtime_scales, o.objective_scale])].sort((a, b) => a - b)
  const stats = [...new Set([...o.statistics, o.objective_statistic])]
  return {
    title: title || undefined, scenario_type: scenarioType || undefined, scenario_ids: scenarioIds,
    spec: {
      axes: { statistics: stats, runtime_scales: scales, dvfs_headroom_levels: o.dvfs_headroom_levels,
        compression: { enabled: o.modes.length > 0 && o.max_buffers > 0, modes: o.modes.length ? o.modes : ['lossy'], max_buffers: o.max_buffers } },
      constraints: { allow_lossy: o.allow_lossy },
      objective: { statistic: o.objective_statistic, runtime_scale: o.objective_scale },
    },
  }
}

/** Case count per variant before running (guards the 200k server limit). */
export function caseCount(o: RunOptions, domains = 3): number {
  const slices = new Set([...o.statistics, o.objective_statistic]).size * new Set([...o.runtime_scales, o.objective_scale]).size
  const comp = o.modes.length ? 2 ** o.max_buffers : 1
  return slices * comp * (o.dvfs_headroom_levels + 1) ** domains
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetchAdmitted(`${API_BASE}${path}`, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined })
  if (!res.ok) {
    let detail = ''
    try { const j = await res.json() as { detail?: unknown }; detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j) } catch { /* not json */ }
    throw new ApiError(`${res.status} ${res.statusText} — ${path}${detail ? ` · ${detail}` : ''}`, res.status)
  }
  return res.json() as Promise<T>
}
const q = (p: Record<string, string | undefined>) => { const s = new URLSearchParams(Object.entries(p).filter(([, v]) => v) as [string, string][]).toString(); return s ? `?${s}` : '' }

export const archApi = {
  runs: () => send<RunMeta[]>('GET', '/arch/exploration/runs'),
  run: (id: string) => send<RunDetail>('GET', `/arch/exploration/runs/${encodeURIComponent(id)}`),
  createRun: (body: ReturnType<typeof runBody>) => send<RunDetail>('POST', '/arch/exploration/runs', body),
  promote: (runId: string, variantIds?: string[], caseKey?: string, reason?: string) =>
    send<{ promoted: { id: string; variant_id: string; total_mw: number }[]; skipped: { variant_id: string; reason: string }[] }>(
      'POST', '/arch/predictions/promote', { run_id: runId, variant_ids: variantIds, case_key: caseKey, reason }),
  board: (scenarioId?: string) => send<{ rows: BoardRow[] }>('GET', `/arch/predictions/board${q({ scenario_id: scenarioId })}`),
  history: (scenarioId: string, variantId: string) => send<HistoryRow[]>('GET', `/arch/predictions/history${q({ scenario_id: scenarioId, variant_id: variantId })}`),
  compare: (p: { old_id?: string; new_id?: string; scenario_id?: string; variant_id?: string }) =>
    send<{ old: HistoryRow; new: HistoryRow; attribution: Attribution }>('GET', `/arch/predictions/compare${q(p)}`),
  reports: () => send<ReportMeta[]>('GET', '/arch/reports'),
  createReport: (runId: string, title?: string) => send<ReportMeta>('POST', '/arch/reports', { run_id: runId, title }),
  setReportStatus: (id: string, status: 'draft' | 'published') => send<ReportMeta>('PATCH', `/arch/reports/${encodeURIComponent(id)}`, { status }),
  reportStale: (id: string) => send<{ stale: boolean; changed: { variant_id: string }[] }>('GET', `/arch/reports/${encodeURIComponent(id)}/stale`),
  reportHtmlUrl: (id: string) => `${API_BASE}/arch/reports/${encodeURIComponent(id)}/html`,
}

// ---------------------------------------------------------------- helpers
// Power components: blue / green / orange (Okabe-Ito — separable incl. color-vision deficiency)
export const PCOL = { cpu: '#0072B2', bwcpu: '#56B4E9', hw: '#009E73', bw: '#E69F00', total: '#4A5160' } as const
export const METRIC_COLOR: Record<DistKey, string> = {
  total_mw: PCOL.total, cpu_mw: PCOL.cpu, hw_mw: PCOL.hw, bw_mw: PCOL.bw, bw_ip_mw: PCOL.bw, bw_cpu_mw: PCOL.bwcpu,
  bw_mbs: PCOL.bw, bw_ip_mbs: PCOL.bw, bw_cpu_mbs: PCOL.bwcpu,
}

/** Stack order CPU → CPU BW → IP core → IP BW (runs from engine rev 1 have only total BW → shown as IP BW). */
export function powerParts(p: Power): { key: 'cpu' | 'bwcpu' | 'hw' | 'bw'; label: string; mw: number }[] {
  const cpuBw = p.bw_cpu_mw ?? 0
  const ipBw = p.bw_ip_mw ?? p.bw_mw - cpuBw
  return [
    { key: 'cpu', label: 'CPU (SW)', mw: p.cpu_mw }, { key: 'bwcpu', label: 'CPU BW', mw: cpuBw },
    { key: 'hw', label: 'IP (HW core)', mw: p.hw_mw }, { key: 'bw', label: 'IP BW', mw: ipBw },
  ]
}
export const short = (v: string) => v.replace(/^cam-rec-/, '').replace(/^cam-prev-/, 'prev-')
export const levels = (d: Record<string, number> | undefined) => Object.entries(d ?? {}).sort().map(([k, v]) => `${k}:L${v}`).join(' ')

/** Case delta vs the recommended case, per component. */
export function caseDelta(c: ExpCase, ref: ExpCase) {
  return { total: c.total_mw - ref.total_mw, cpu: c.cpu_mw - ref.cpu_mw, hw: c.hw_mw - ref.hw_mw, bw: c.bw_mw - ref.bw_mw, bw_mbs: c.bw_mbs - ref.bw_mbs }
}

/** Waterfall steps for an attribution (top N factors + '기타'). */
export function waterfall(a: Attribution, n = 10): { label: string; start: number; end: number; delta: number; category: string }[] {
  const top = a.factors.slice(0, n)
  const rest = a.factors.slice(n).reduce((s, f) => s + f.delta_mw, 0) + a.residual_mw
  const steps: { label: string; start: number; end: number; delta: number; category: string }[] = []
  let cur = a.old_total_mw
  for (const f of top) { steps.push({ label: `${f.item}`, start: cur, end: cur + f.delta_mw, delta: f.delta_mw, category: f.category }); cur += f.delta_mw }
  if (Math.abs(rest) >= 0.05) { steps.push({ label: '기타', start: cur, end: cur + rest, delta: rest, category: '기타' }); cur += rest }
  return steps
}

export const CAT_COLOR: Record<string, string> = {
  'SW runtime': '#0072B2', 'SW task 추가': '#0072B2', 'SW task 제거': '#0072B2',
  'IP workload': '#009E73', 'IP 추가': '#009E73', 'IP 제거': '#009E73', 'IP DVFS 전압': '#56B4E9',
  'BW traffic': '#E69F00', Compression: '#D55E00', 기타: '#9A9387',
}
