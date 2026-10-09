// 예측 현황 · Risk & Focus: per registered prediction, what threatens the customer's performance / thermal
// target and which lever (CPU · IP clock · BW · power option) to work on first. Pure rules over the board row,
// measurement coverage and an optional power target, so the page and the tests share one implementation.
import type { BoardRow } from './archExplore'

export type RiskLevel = 'high' | 'med' | 'low' | 'ok'
export type RiskKind = 'perf' | 'thermal' | 'confidence'
export interface RiskItem { kind: RiskKind; level: Exclude<RiskLevel, 'ok'>; text: string }
export interface FocusItem { lever: 'cpu' | 'ip' | 'bw' | 'option' | 'clock' | 'measure'; text: string; gain_mw?: number | null; page?: string }
export interface RiskRow {
  row: BoardRow; level: RiskLevel; score: number; risks: RiskItem[]; focus: FocusItem[]
  /** target gap: positive = over the target (mW) */
  gap_mw: number | null; dominant: { part: 'CPU' | 'IP' | 'BW'; mw: number; share: number }
  min_slack_pct: number | null
}
export interface RiskContext {
  /** customer power (thermal) target in mW for every row; null = no target, power risk is relative only */
  target_mw: number | null
  /** real measurements per variant key `${scenario}|${variant}`; undefined = unknown (coverage API unavailable) */
  measured?: Map<string, number>
}

const RANK: Record<RiskLevel, number> = { high: 3, med: 2, low: 1, ok: 0 }
export const RISK_LABEL: Record<RiskLevel, string> = { high: '높음', med: '중간', low: '낮음', ok: '양호' }
export const RISK_CLASS: Record<RiskLevel, string> = { high: 'v-fail', med: 'v-warn', low: 'v-info', ok: 'v-ok' }
export const KIND_LABEL: Record<RiskKind, string> = { perf: '성능', thermal: '발열·power', confidence: '예측 신뢰도' }

/** Smallest SW slack over the frozen stages, as % of the frame period. budget_ms is the HW budget, which for NRT / Post
 *  already excludes the SW time (period − SW), so slack = budget − HW for every stage. */
export function minSlackPct(r: BoardRow): number | null {
  const d = r.verdict_detail
  const period = d?.period_ms ?? (r.fps ? 1000 / r.fps : null)
  if (!d?.stages?.length || !period) return null
  const vals = d.stages.filter((s) => s.budget_ms !== undefined && s.budget_ms > 0 && s.hw_ms !== undefined && s.hw_ms > 0)
    .map((s) => ((s.budget_ms! - s.hw_ms!) / period) * 100)
  return vals.length ? Math.min(...vals) : null
}

export function assessRisk(r: BoardRow, ctx: RiskContext, peers: BoardRow[] = []): RiskRow {
  const risks: RiskItem[] = []
  const focus: FocusItem[] = []
  const p = r.power
  const parts = [{ part: 'CPU' as const, mw: p.cpu_mw }, { part: 'IP' as const, mw: p.hw_mw }, { part: 'BW' as const, mw: p.bw_mw }]
  const top = parts.reduce((a, b) => (b.mw > a.mw ? b : a))
  const dominant = { ...top, share: p.total_mw > 0 ? top.mw / p.total_mw : 0 }

  // ---- performance (customer fps)
  const slack = minSlackPct(r)
  if (r.verdict === 'fail') risks.push({ kind: 'perf', level: 'high', text: `timing 미달 — ${r.verdict_detail?.reasons?.[0] ?? '현재 clock으로 fps 못 맞춤'}` })
  else if (r.verdict === 'clock_up') risks.push({ kind: 'perf', level: 'med', text: `NRT clock ↑ 필요${r.verdict_detail?.nrt_clock_factor ? ` (×${r.verdict_detail.nrt_clock_factor.toFixed(2)})` : ''} — 올리면 power ↑` })
  // clock_up / fail already say the stage does not fit; the frozen slack would repeat it
  if (slack !== null && r.verdict === 'ok') {
    if (slack < 0) risks.push({ kind: 'perf', level: 'high', text: `SW 여유 ${slack.toFixed(0)}% (음수) — SW 증가 시 바로 frame drop` })
    else if (slack < 10) risks.push({ kind: 'perf', level: 'med', text: `SW 여유 ${slack.toFixed(0)}% of frame — 차기 SW 증가(×1.1~1.3)에 취약` })
  }

  // ---- thermal / power (customer target)
  let gap: number | null = null
  if (ctx.target_mw && ctx.target_mw > 0) {
    gap = p.total_mw - ctx.target_mw
    if (gap > 0) risks.push({ kind: 'thermal', level: 'high', text: `목표 ${ctx.target_mw.toFixed(0)} mW 초과 +${gap.toFixed(0)} mW` })
    else if (p.total_mw > 0.9 * ctx.target_mw) risks.push({ kind: 'thermal', level: 'med', text: `목표의 ${((100 * p.total_mw) / ctx.target_mw).toFixed(0)}% — 여유 ${(-gap).toFixed(0)} mW` })
  } else if (peers.length >= 4) {
    const sorted = peers.map((x) => x.power.total_mw).sort((a, b) => a - b)
    const p80 = sorted[Math.floor(0.8 * (sorted.length - 1))]
    if (p.total_mw >= p80 && p.total_mw > sorted[0]) risks.push({ kind: 'thermal', level: 'low', text: `상위 20% power (${p.total_mw.toFixed(0)} mW) — 목표 미설정, 상대 비교` })
  }

  // ---- confidence (is the number trustworthy enough to commit to the customer?)
  const meas = ctx.measured?.get(`${r.scenario_id}|${r.variant_id}`)
  const nearTarget = gap === null || gap > -0.1 * (ctx.target_mw ?? 0)
  if (ctx.measured && !meas) risks.push({ kind: 'confidence', level: gap !== null && nearTarget ? 'med' : 'low', text: '실측 없음 — 예측만으로 판단' })
  if (r.verified && !r.verified.ok) risks.push({ kind: 'confidence', level: 'med', text: `sim 검증 불일치${r.verified.delta_pct !== null ? ` ${r.verified.delta_pct.toFixed(1)}%` : ''}` })
  const dist = r.distribution?.total_mw
  if (dist && p.total_mw > 0 && (dist.max - dist.min) / p.total_mw > 0.25)
    risks.push({ kind: 'confidence', level: 'low', text: `조합·SW 통계에 따라 ${dist.min.toFixed(0)}–${dist.max.toFixed(0)} mW — 조건 확정 필요` })

  // ---- focus: biggest lever first
  const opt = r.power_options?.best
  if (opt && opt.delta_mw < 0) focus.push({ lever: 'option', text: `power option ${opt.labels.join(' + ')} (IQ 평가 필요)`, gain_mw: opt.delta_mw, page: 'explore' })
  if (dominant.part === 'CPU') focus.push({ lever: 'cpu', text: `CPU ${p.cpu_mw.toFixed(0)} mW (${(100 * dominant.share).toFixed(0)}%) — MID 분산/EMS · traffic shaping 검토`, page: 'cpu' })
  else if (dominant.part === 'IP') focus.push({ lever: 'ip', text: `IP ${p.hw_mw.toFixed(0)} mW (${(100 * dominant.share).toFixed(0)}%) — DVFS level ±1 · IP mode 검토`, page: 'timing' })
  else focus.push({ lever: 'bw', text: `BW ${p.bw_mw.toFixed(0)} mW (${(100 * dominant.share).toFixed(0)}%) — compression · LLC · buffer 크기`, page: 'pipeline' })
  if (r.verdict === 'clock_up' || r.verdict === 'fail') focus.push({ lever: 'clock', text: 'SW 단축 또는 pipeline buffering으로 clock ↑ 회피 (Timing Budget)', page: 'timing' })
  else if (slack !== null && slack > 30) focus.push({ lever: 'clock', text: `SW 여유 ${slack.toFixed(0)}% — IP clock level ↓ 여지 (Timing Budget ⑦)`, page: 'timing' })
  if (ctx.measured && !meas && nearTarget) focus.push({ lever: 'measure', text: '실측으로 예측 검증 (Calibration)', page: 'calibration' })

  const level = risks.reduce<RiskLevel>((a, x) => (RANK[x.level] > RANK[a] ? x.level : a), 'ok')
  const score = risks.reduce((s, x) => s + RANK[x.level] * (x.kind === 'confidence' ? 0.5 : 1), 0) + (gap !== null && gap > 0 ? gap / 100 : 0)
  return { row: r, level, score, risks, focus, gap_mw: gap, dominant, min_slack_pct: slack }
}

export function assessAll(rows: BoardRow[], ctx: RiskContext): RiskRow[] {
  return rows.map((r) => assessRisk(r, ctx, rows))
    .sort((a, b) => RANK[b.level] - RANK[a.level] || b.score - a.score || b.row.power.total_mw - a.row.power.total_mw)
}
