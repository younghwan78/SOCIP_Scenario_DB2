// Number provenance (U1), model status (U2), verdict reasons (U4), calibration fit (U6) and
// report scoping (U7). Until the engines are unified in-house, the same variant can show
// different power on different pages; these helpers make each number say where it came from.
import type { ReportMeta } from './archExplore'
import { getJson } from './api'

export type ProvKind = 'registered' | 'recalc' | 'simulation' | 'measured' | 'synthetic'
export interface Prov {
  kind: ProvKind
  /** engine that produced the number, e.g. 'Timing Budget (analytic)' */
  engine?: string
  /** power terms covered, e.g. 'CPU + IP + BW' */
  scope?: string
  /** engine / model revision */
  rev?: string | null
  dvfs?: string | null
  id?: string | null
  at?: string | null
  notes?: string[]
}

export const PROV_LABEL: Record<ProvKind, string> = {
  registered: '등록', recalc: '재계산', simulation: 'Sim evidence', measured: '실측', synthetic: '합성',
}

export const isSampleRef = (ref?: string | null): boolean => !!ref && /sample|synthetic/i.test(ref)

/** Multi-line tooltip text for a provenance badge. */
export function provText(p: Prov): string {
  const lines = [`출처: ${PROV_LABEL[p.kind]}${p.engine ? ` · ${p.engine}` : ''}`]
  if (p.scope) lines.push(`범위: ${p.scope}`)
  if (p.rev) lines.push(`model: ${p.rev}`)
  if (p.dvfs) lines.push(`DVFS: ${p.dvfs}${isSampleRef(p.dvfs) ? ' (SAMPLE)' : ''}`)
  if (p.id) lines.push(`id: ${p.id}`)
  if (p.at) lines.push(`생성: ${p.at.slice(0, 16).replace('T', ' ')}`)
  for (const n of p.notes ?? []) lines.push(n)
  return lines.join('\n')
}

/** Power terms a CPU/IP/BW split covers; a source without a CPU term does not include SW power. */
export function powerScope(split: { cpu?: number | null; ip?: number | null; hw?: number | null; bw?: number | null } | null | undefined): string {
  if (!split) return '—'
  const parts: string[] = []
  if ((split.cpu ?? 0) > 0) parts.push('CPU')
  if ((split.ip ?? split.hw ?? 0) > 0) parts.push('IP')
  if ((split.bw ?? 0) > 0) parts.push('BW')
  return parts.length ? parts.join(' + ') : '—'
}

// ------------------------------------------------------------------ U7 reports
/** Reports of the selected project first; other projects are listed separately, never opened by default. */
export function reportsForProject(list: ReportMeta[], project: string): { mine: ReportMeta[]; others: ReportMeta[] } {
  return { mine: list.filter((r) => r.project_ref === project), others: list.filter((r) => r.project_ref !== project) }
}

// ------------------------------------------------------------------ U4 verdict
export type IssueCode = 'sw_budget' | 'rt_budget' | 'interval' | 'ip_clock' | 'other'
export interface Issue { code: IssueCode; label: string; detail: string }
export const ISSUE_LABEL: Record<IssueCode, string> = {
  sw_budget: 'SW > 예산', rt_budget: 'RT HW > 75%', interval: '출력 간격', ip_clock: 'IP clock 불가', other: '기타',
}
export const ISSUE_ORDER: IssueCode[] = ['sw_budget', 'rt_budget', 'interval', 'ip_clock', 'other']

const RE_SW = /^(.+?): SW ([\d.]+) ms leaves no HW budget$/
const RE_RT = /^RT HW ([\d.]+) ms > 75% budget ([\d.]+) ms$/
const RE_IV = /^(preview|video) interval ([\d.]+) ms != ([\d.]+) ms$/
const RE_IP = /^([A-Za-z0-9_.-]+): (.+)$/

/** Structured issues from timing-budget verdict reasons (sim/timing_budget.py `_verdict`). */
export function verdictIssues(reasons: string[]): Issue[] {
  const out: Issue[] = []
  const seen = new Set<string>()
  const ip: Record<string, { node: string; detail: string }[]> = {}
  const push = (i: Issue) => { const k = `${i.code}:${i.label}`; if (!seen.has(k)) { seen.add(k); out.push(i) } }
  for (const r of reasons) {
    let m: RegExpExecArray | null
    if ((m = RE_SW.exec(r))) push({ code: 'sw_budget', label: `${m[1]} SW ${Number(m[2]).toFixed(1)} ms`, detail: r })
    else if ((m = RE_RT.exec(r))) push({ code: 'rt_budget', label: `RT ${Number(m[1]).toFixed(1)}>${Number(m[2]).toFixed(1)} ms`, detail: r })
    else if ((m = RE_IV.exec(r))) push({ code: 'interval', label: `${m[1]} ${Number(m[2]).toFixed(2)}≠${Number(m[3]).toFixed(2)} ms`, detail: r })
    else if ((m = RE_IP.exec(r))) { const k = ipKind(m[2]); (ip[k] ??= []).push({ node: m[1], detail: r }) }
    else push({ code: 'other', label: r.length > 24 ? `${r.slice(0, 24)}…` : r, detail: r })
  }
  // one badge per IP failure kind: "DVFS max 초과 · byrp 외 7" (detail lists every IP)
  for (const [kind, nodes] of Object.entries(ip)) {
    push({ code: 'ip_clock', label: `${kind} · ${nodes[0].node}${nodes.length > 1 ? ` 외 ${nodes.length - 1}` : ''}`, detail: nodes.map((n) => n.detail).join('\n') })
  }
  return out
}

/** dvfs_resolver.py infeasible_reason → short kind. */
function ipKind(msg: string): string {
  if (/exceeds max DVFS speed/.test(msg)) return 'DVFS max 초과'
  if (/exceeds ip max_clock|exceeds supported clock/.test(msg)) return 'IP max clock 초과'
  if (/override level not found/.test(msg)) return 'DVFS level 없음'
  if (/set_clock .* < required_clock/.test(msg)) return 'override level 부족'
  return 'clock 불가'
}

/** Count of rows per issue code (a row with two interval issues counts once). */
export function issueCounts(rowsReasons: string[][]): Record<IssueCode, number> {
  const c: Record<IssueCode, number> = { sw_budget: 0, rt_budget: 0, interval: 0, ip_clock: 0, other: 0 }
  for (const rs of rowsReasons) for (const code of new Set(verdictIssues(rs).map((i) => i.code))) c[code] += 1
  return c
}

// ------------------------------------------------------------------ U6 calibration
export interface CategoryFit { worst_category: string | null; worst_delta_pct: number | null; offsetting: boolean }
/** Total |Δ| ≤ 10% while a modelled category is off by > 25%: the total matches by compensation. */
export const OFFSET_TOTAL_PCT = 10
export const OFFSET_CATEGORY_PCT = 25

export function categoryFit(rows: { category: string; delta_pct: number | null }[] | null | undefined, totalDeltaPct: number | null | undefined): CategoryFit {
  let worst: { category: string; delta_pct: number } | null = null
  for (const r of rows ?? []) {
    if (r.delta_pct === null || r.delta_pct === undefined) continue
    if (!worst || Math.abs(r.delta_pct) > Math.abs(worst.delta_pct)) worst = { category: r.category, delta_pct: r.delta_pct }
  }
  const offsetting = !!worst && totalDeltaPct !== null && totalDeltaPct !== undefined
    && Math.abs(totalDeltaPct) <= OFFSET_TOTAL_PCT && Math.abs(worst.delta_pct) > OFFSET_CATEGORY_PCT
  return { worst_category: worst?.category ?? null, worst_delta_pct: worst?.delta_pct ?? null, offsetting }
}

// ------------------------------------------------------------------ U2 model status
export interface ModelStatus {
  engine_rev: string
  project_ref: string | null
  predictions: { current: number; stale_engine: number; engines: Record<string, number> }
  dvfs: { ref: string; sample: boolean; predictions: number }[]
  measurements: { real: number; synthetic: number }
  lineage: Record<string, unknown> | null
}
export type StatusLevel = 'ok' | 'warn' | 'info'
export interface StatusItem { key: string; text: string; title: string; level: StatusLevel; href?: string }

export function statusItems(s: ModelStatus, project?: string): StatusItem[] {
  const q = project ? `?project=${encodeURIComponent(project)}` : ''
  const items: StatusItem[] = []
  const sample = s.dvfs.filter((d) => d.sample)
  items.push(s.dvfs.length === 0
    ? { key: 'dvfs', text: 'DVFS 미연결', title: '등록 예측이 참조하는 DVFS table 없음', level: 'warn', href: `#/library${q}` }
    : sample.length
      ? { key: 'dvfs', text: `DVFS SAMPLE ${sample.length}/${s.dvfs.length}`, title: `사내 table 교체 필요: ${sample.map((d) => d.ref).join(', ')}`, level: 'warn', href: `#/library${q}` }
      : { key: 'dvfs', text: `DVFS ${s.dvfs.map((d) => d.ref).join(', ')}`, title: '등록 예측이 참조하는 DVFS table', level: 'ok', href: `#/library${q}` })
  const m = s.measurements
  items.push({ key: 'meas', text: `실측 ${m.real} · 합성 ${m.synthetic}`,
    title: m.real === 0 ? '실제 silicon 측정이 없어 예측 정확도를 검증할 수 없음 (합성 fixture는 검증 근거 아님)' : '실제 silicon 측정 / 합성 fixture 건수',
    level: m.real === 0 ? 'warn' : 'ok', href: `#/calibration${q}` })
  const p = s.predictions
  items.push(p.current === 0
    ? { key: 'pred', text: '등록 예측 없음', title: '조합 탐색에서 등록', level: 'info', href: `#/explore${q}` }
    : p.stale_engine > 0
      ? { key: 'pred', text: `등록 예측 ${p.stale_engine}/${p.current} 이전 model`, title: `현재 engine ${s.engine_rev} 이전 run에서 등록됨: ${Object.entries(p.engines).map(([e, n]) => `${e} ${n}`).join(', ')} → 재탐색 필요`, level: 'warn', href: `#/explore${q}` }
      : { key: 'pred', text: `등록 예측 ${p.current}`, title: `모두 ${s.engine_rev}`, level: 'ok', href: `#/predictions${q}` })
  const lin = s.lineage ?? {}
  const model = [lin.power_model, lin.bw_power_model].filter(Boolean).join(' · ')
  items.push({ key: 'model', text: `engine ${s.engine_rev}${model ? ` · ${model}` : ''}`, title: Object.entries(lin).map(([k, v]) => `${k}: ${String(v)}`).join('\n') || '최근 탐색 run의 model lineage 없음', level: 'info' })
  return items
}

export const provenanceApi = {
  modelStatus: (projectRef?: string) => getJson<ModelStatus>('/arch/model-status', { project_ref: projectRef }, false),
}
