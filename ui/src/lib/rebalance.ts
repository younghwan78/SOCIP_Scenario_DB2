// CPU what-if "MID 재분배": split movable tasks over a cluster pool (POST /cpu/rebalance).
import { postAdmitted } from './timingBudget'
import type { CpuSweepRequest } from './cpu'
import { dsuPower, residency, type DsuModelInfo, type DsuParams, type DsuPolicy } from './dsu'

export interface RbSplit {
  assign: Record<string, string>; moved: string[]; total_mw: number; delta_mw: number; feasible: boolean
  mw: Record<string, number>; mhz: Record<string, number>; mv: Record<string, number>
  busy_mhz: Record<string, number>; dsu_active: number
  knobs: { tasks: string[]; kind: string; clusters: string[] }[]
  rank?: number; step?: number; moved_unit?: string | null; moved_util_pct?: number
  task_ms?: Record<string, number>; slack_ms?: Record<string, number>; min_slack_ms?: number | null
  flags?: Record<string, string[] | boolean>; verified?: boolean; model_err_mw?: number
  clusters?: Record<string, { mhz: number; busy_ms: number; total_mw: number; util: number }>
  dsu?: { mhz: number; active_ratio: number; total_mw: number } | null
  label?: string
}
export interface RbUnit { unit: string; tasks: string[]; home: string; budget_ms: number | null; threads: number; util_fmax: Record<string, number>; t_fmax_ms: Record<string, number> }
export interface RbBoundary { cluster: string; mhz: number; mv: number; peak_cpu_util: number; capacity: number; sched_mhz?: number; boosted_by?: string[]; next_lower_mhz?: number; next_lower_mv?: number; delta_util_needed?: number; candidates?: [string, number][] }
export interface RbState { mhz: Record<string, number>; count: number; min_mw: number; max_mw: number; representative: Record<string, string>; rep_mw: Record<string, number>; busy_mhz: Record<string, number>; dsu_active: number }
export interface RbStrategyRow {
  kind: 'concentrate' | 'spread'; clusters: string[]; ways: number; total_mw: number; delta_mw: number; feasible: boolean
  mhz: Record<string, number>; mw: Record<string, number>; assign: Record<string, string>; moved: string[]; min_slack_ms?: number | null
}
export interface RbBigMove { unit: string; cluster: string; total_mw: number; delta_mw: number; feasible: boolean; mhz: number; dsu_mhz: number }
export interface RbStrategies {
  rows: RbStrategyRow[]; best_concentrate: RbStrategyRow | null; best_spread: RbStrategyRow | null
  winner: 'concentrate' | 'spread' | 'tie' | 'none'; spread_gain_mw: number | null; complete: boolean
  big_check: { clusters: string[]; base_mw: number; base_assign: Record<string, string>; moves: RbBigMove[]; best: RbBigMove | null; gain: boolean } | null
}
export interface CpuRebalance {
  fps: number; period_ms: number; pool: string[]; default_pool: string[]
  clusters: { name: string; core_type: string | null; cores: number; in_pool: boolean; opps_mhz: number[]; capacity: number }[]
  units: RbUnit[]; frozen: string[]; symmetric: string[][]
  space: number; evaluated: number; cluster_states: number; method: 'exhaustive' | 'local'; feasible_count: number; verified: number
  reference: RbSplit; best: RbSplit | null; cases: RbSplit[]; opp_states: RbState[]; opp_state_count: number; curve: RbSplit[]
  /** concentrate vs spread over the pool + BIG check (absent on older servers) */
  strategies?: RbStrategies
  boundaries: { reference: RbBoundary[]; best: RbBoundary[] }
  dsu_model: DsuModelInfo | null; dsu_params: DsuParams | null; dsu_measured?: Record<string, number> | null; warnings: string[]
  /** CPU → DRAM traffic after cpu_bw_scale (API ≥ 2026-10-09); CPU + DSU power does not depend on it */
  cpu_bw_mbs?: number
}
export interface CpuRebalanceRequest extends CpuSweepRequest {
  pool: string[]; movable?: string[]; locks: Record<string, string>; co_move: string[][]; verify_k?: number; max_exhaustive?: number
}
export const rebalanceApi = {
  run: (req: CpuRebalanceRequest) => postAdmitted<{ result: CpuRebalance }>('/cpu/rebalance', req).then((r) => r.result),
}

/** One-line reading of the concentrate / spread / BIG result for the strategy card. */
export function strategyVerdict(s: RbStrategies): { text: string; tone: 'ok' | 'warn' | '' } {
  const c = s.best_concentrate, p = s.best_spread
  if (!c && !p) return { text: 'budget을 만족하는 분배가 없습니다 — budget·SW 부하 가정을 확인하세요.', tone: 'warn' }
  const name = (r: RbStrategyRow) => r.clusters.join(' + ')
  if (s.winner === 'spread' && c && p) return { text: `분산이 유리: ${name(p)}에 나누면 ${name(c)} 한 곳 집중보다 ${s.spread_gain_mw?.toFixed(1)} mW 낮습니다 (OPP가 내려감).`, tone: 'ok' }
  if (s.winner === 'concentrate' && c && p) return { text: `집중이 유리: ${name(c)} 한 곳에 두면 분산(${name(p)})보다 ${Math.abs(s.spread_gain_mw ?? 0).toFixed(1)} mW 낮습니다 (다른 cluster를 깨우는 비용 > OPP 절감).`, tone: 'ok' }
  if (s.winner === 'tie') return { text: '집중과 분산의 차이가 작습니다 — 응답성(slack)·thermal 기준으로 고르세요.', tone: '' }
  return { text: c ? `한 곳 집중만 budget을 만족합니다 (${name(c)}).` : `분산만 budget을 만족합니다 (${name(p!)}).`, tone: 'warn' }
}

export function bigVerdict(b: NonNullable<RbStrategies['big_check']>): { text: string; tone: 'ok' | 'warn' } {
  const m = b.best
  if (!m) return { text: `${b.clusters.join(', ')}로 옮기면 모두 budget 미충족입니다.`, tone: 'ok' }
  if (b.gain) return { text: `${m.unit} → ${m.cluster} 이동이 ${Math.abs(m.delta_mw).toFixed(1)} mW 낮습니다 — 고부하(BW·고속) 조건이면 BIG 사용을 검토하세요.`, tone: 'warn' }
  return { text: `BIG 사용 이득 없음: 가장 유리한 경우(${m.unit} → ${m.cluster})도 +${m.delta_mw.toFixed(1)} mW.`, tone: 'ok' }
}

/** client default pool when no result yet: clusters whose name has no "BIG" (≥ 2), else all */
export function defaultPool(names: string[]): string[] {
  const p = names.filter((n) => !/big/i.test(n))
  return p.length >= 2 ? p : names
}

function reDsu(s: { total_mw: number; mw: Record<string, number>; busy_mhz: Record<string, number>; dsu_active: number }, pol: DsuPolicy, p: DsuParams, measured?: Record<string, number> | null) {
  const d = dsuPower(p, residency(pol, p, s.busy_mhz, measured), s.dsu_active)
  return { total: s.total_mw - (s.mw.dsu ?? 0) + d.total_mw, dsuMw: d.total_mw, dsuMhz: d.mhz }
}

/** Re-evaluate the DSU of every returned split for another rule; re-rank cases and OPP states (cluster OPPs fixed). */
export function applyDsuRebalance(r: CpuRebalance, pol: DsuPolicy | null): CpuRebalance {
  const p = r.dsu_params
  if (!pol || !p) return r
  const fix = (s: RbSplit, refTotal?: number): RbSplit => {
    const x = reDsu(s, pol, p, r.dsu_measured)
    return { ...s, total_mw: x.total, mw: { ...s.mw, dsu: x.dsuMw }, mhz: { ...s.mhz, dsu: x.dsuMhz }, delta_mw: refTotal === undefined ? 0 : x.total - refTotal }
  }
  const reference = fix(r.reference)
  const cases = r.cases.map((c) => fix(c, reference.total_mw)).sort((a, b) => a.total_mw - b.total_mw || a.moved.length - b.moved.length).map((c, i) => ({ ...c, rank: i + 1 }))
  const curve = r.curve.map((c) => fix(c, reference.total_mw))
  const opp_states = r.opp_states.map((s) => {
    const x = reDsu({ total_mw: s.min_mw, mw: s.rep_mw, busy_mhz: s.busy_mhz, dsu_active: s.dsu_active }, pol, p, r.dsu_measured)
    const shift = x.total - s.min_mw
    return { ...s, min_mw: x.total, max_mw: s.max_mw + shift, mhz: { ...s.mhz, dsu: x.dsuMhz }, rep_mw: { ...s.rep_mw, dsu: x.dsuMw } }
  }).sort((a, b) => a.min_mw - b.min_mw)
  return { ...r, reference, cases, best: cases[0] ?? null, curve, opp_states,
    dsu_model: { mode: pol.mode, requested: pol.mode, source: 'experiment', vote: pol.vote, fixed_mhz: pol.fixed_mhz } }
}
