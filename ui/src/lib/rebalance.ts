// CPU what-if "MID 재분배": split movable tasks over a cluster pool (POST /cpu/rebalance).
import { postCalculation } from './calculation'
import type { CpuSweepRequest } from './cpu'
import { dsuPower, residency, type DsuModelInfo, type DsuParams, type DsuPolicy } from './dsu'
import { fmt } from './timingBudget'

export interface RbSplit {
  assign: Record<string, string>; moved: string[]; total_mw: number; delta_mw: number; feasible: boolean
  mw: Record<string, number>; mhz: Record<string, number>; mv: Record<string, number>
  busy_mhz: Record<string, number>; dsu_active: number
  knobs: { tasks: string[]; kind: string; clusters: string[] }[]
  rank?: number; step?: number; moved_unit?: string | null; moved_util_pct?: number
  task_ms?: Record<string, number>; slack_ms?: Record<string, number>; min_slack_ms?: number | null
  /** API ≥ 2026-10-28, shared CPU only: own + same-CPU co-runner time (upper bound) and the budget slack against it */
  response_ms?: Record<string, number>; min_slack_shared_ms?: number | null
  /** only with scheduler.task_policy sched_class: shared-CPU response with the class / priority (RT preempts, nice share) */
  response_prio_ms?: Record<string, number>; min_slack_prio_ms?: number | null
  flags?: Record<string, string[] | boolean>; verified?: boolean; model_err_mw?: number
  clusters?: Record<string, { mhz: number; busy_ms: number; total_mw: number; util: number }>
  dsu?: { mhz: number; active_ratio: number; total_mw: number } | null
  label?: string
}
export interface TaskSched { sched_class: 'fifo' | 'rr' | 'normal'; rt_priority?: number; nice?: number }
export interface RbUnit { unit: string; tasks: string[]; home: string; budget_ms: number | null; budget_source?: 'user' | 'stretch' | null; threads: number; util_fmax: Record<string, number>; t_fmax_ms: Record<string, number> }
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
  /** API ≥ 2026-10-11: task budgets in effect and where they came from (user / stretch = Timing Budget) */
  budgets_ms?: Record<string, number>; budget_source?: Record<string, 'user' | 'stretch'>
  /** API ≥ 2026-10-11: the variant's Timing Budget stages, enforced (stage_slack) or only reported (off) */
  timing_coupling?: TimingCoupling
  /** API ≥ 2026-10-11: why the best split wins (OPP change per cluster, moves, stretched tasks) */
  why?: RbWhy | null
  /** CPU-07: units moved one at a time onto one target cluster (x = share of movable util on it) */
  ratio_curves?: RatioCurve[]
  /** CPU-09: CPU-caused DRAM BW power with the exploration's BW coefficient */
  bw_power?: BwPower
  /** API ≥ 2026-10-28: the timing mode the result was computed with */
  timing_mode?: 'off' | 'stage_slack'
  /** stage_slack + latency_trade: what a longer pipeline latency (period-only search) would buy */
  latency_trade?: LatencyTrade | null
  /** scheduling class / priority from scheduler.task_policy (absent when none is set; unset tasks = normal nice 0) */
  task_sched?: Record<string, TaskSched>
  /** API ≥ 2026-11-01: RT thread placement inside a cluster (eas | cpupri) */
  rt_placement?: 'eas' | 'cpupri'
}
export interface LatencyTrade { best_total_mw: number; moved: string[]; delta_mw: number; delta_vs_reference_mw: number; extra_latency_frames: number; min_slack_ms: number | null; impact: TimingImpact[] }
export interface RatioPoint { util_pct: number; moved_unit: string | null; total_mw: number; feasible: boolean; mhz: Record<string, number> }
export interface RatioCurve { target: string; start_util_pct: number; points: RatioPoint[]; best_index: number | null }
export interface BwCoefficient { mw_per_mbs: number; source: 'prediction' | 'builtin'; prediction_ref: string | null; bw_power_model: string | null }
export interface BwPower extends BwCoefficient { cpu_bw_mbs: number | null; bw_mw: number | null; reference_total_mw: number | null; best_total_mw: number | null }
export interface TimingStage {
  stage: string; sw_ms: number; hw_ms: number; overhead_ms: number; room_ms: number; slack_ms: number; stretch: number; tasks: { task: string; ms: number }[]
  /** API ≥ 2026-11-01: SW pairs [a, b] the variant's pipeline orders within one frame (b after a: the RT chain), and whether
   *  that order holds (serial: the stage chain fits one period, so these tasks never run at once) */
  order?: [string, string][]; serial?: boolean
}
export interface TimingImpact { stage: string; sw_ms: number; delta_sw_ms: number; slack_ms: number; chain_ms: number; extra_latency_frames: number; ok: boolean }
export interface TimingCoupling {
  mode: 'stage_slack'; enforced: boolean; scenario_id: string; variant_id: string; statistic: string; runtime_scale: number; period_ms: number
  stages: TimingStage[]; stretch: Record<string, number>; matched_tasks: string[]; unmatched_tasks: string[]
  impact: { reference: TimingImpact[]; best: TimingImpact[] | null }
  serial_pairs?: [string, string][]
}
export interface RbWhy {
  delta_mw: number
  clusters: { cluster: string; mhz: [number, number]; mv: [number, number]; mw: [number, number]; delta_mw: number; opp_change: 'down' | 'up' | 'same' }[]
  dsu: { mhz: [number, number]; mw: [number, number]; delta_mw: number }
  moves: { unit: string; from: string; to: string; util_fmax_to: number | null; ms: [number, number]; stretch: number | null; budget_ms: number | null }[]
  stretched: { task: string; ms: [number, number]; stretch: number; budget_ms: number | null; budget_used_pct: number | null }[]
  driver: { cluster: string; mhz: [number, number]; mv: [number, number]; delta_mw: number; peak_util: number | null; delta_util_needed: number | null; next_lower_mhz: number | null } | null
  budget_limited: string[]
}
export interface CpuRebalanceRequest extends CpuSweepRequest {
  pool: string[]; movable?: string[]; locks: Record<string, string>; co_move: string[][]; verify_k?: number; max_exhaustive?: number
  latency_trade?: boolean
}
export const rebalanceApi = {
  run: (req: CpuRebalanceRequest, signal?: AbortSignal) => postCalculation<{ result: CpuRebalance }>('/cpu/rebalance', req, signal).then((r) => r.result),
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

/** Budget verdict of a split. Own slack (budget − own time) decides feasibility. The wait on a shared CPU only grades it:
 *  with task_policy priorities (``response_prio_ms``) the class / priority response decides 충족 vs 대기 미충족; without them
 *  the bound (every same-CPU co-runner ahead, priority and phase ignored) can only say 조건부. */
export interface SlackVerdict {
  tier: 'ok' | 'shared' | 'wait_miss' | 'unchecked' | 'miss'; task?: string; shared_ms?: number; wait_ms?: number
  /** which wait the tier rests on: scheduling class / priority, or the all-co-runners bound */
  basis?: 'priority' | 'bound'
}
/** task with the lowest budget − response (= own slack − wait) */
function worstWait(s: VerdictInput, response: Record<string, number>): { task: string; shared_ms: number; wait_ms: number } | null {
  let worst: { task: string; shared_ms: number; wait_ms: number } | null = null
  for (const [t, resp] of Object.entries(response)) {
    const own = s.slack_ms?.[t], ms = s.task_ms?.[t]
    if (own === undefined || ms === undefined) continue
    if (!worst || own - (resp - ms) < worst.shared_ms) worst = { task: t, shared_ms: own - (resp - ms), wait_ms: resp - ms }
  }
  return worst
}
/** what a verdict reads: a rebalance split or a sweep case */
export type VerdictInput = Pick<RbSplit, 'feasible' | 'slack_ms' | 'task_ms' | 'response_ms' | 'min_slack_shared_ms' | 'response_prio_ms'>
export function slackVerdict(s: VerdictInput): SlackVerdict {
  if (!s.feasible) return { tier: 'miss' }
  if (s.response_prio_ms) {
    const w = worstWait(s, s.response_prio_ms)
    return w && w.shared_ms < -1e-3 ? { tier: 'wait_miss', basis: 'priority', ...w } : { tier: 'ok', basis: 'priority' }
  }
  // move-curve points come from the search model only: no co-runner check was run (≠ checked with no shared CPU = {})
  if (s.response_ms === undefined && s.min_slack_shared_ms === undefined) return { tier: 'unchecked' }
  const w = worstWait(s, s.response_ms ?? {})
  if (w && w.shared_ms < -1e-3) return { tier: 'shared', basis: 'bound', ...w }
  // older servers send only the minimum
  if (!w && s.min_slack_shared_ms != null && s.min_slack_shared_ms < -1e-3) return { tier: 'shared', basis: 'bound', shared_ms: s.min_slack_shared_ms }
  return { tier: 'ok', basis: 'bound' }
}
export const SLACK_TIER_LABEL: Record<SlackVerdict['tier'], string> = { ok: '충족', shared: '조건부', wait_miss: '대기 미충족', unchecked: '자체 충족', miss: '미충족' }
export function slackVerdictNote(v: SlackVerdict): string {
  if (v.tier === 'ok') return v.basis === 'priority'
    ? 'budget 충족 — 같은 CPU 대기를 스케줄링 클래스 · 우선순위(task_policy)로 계산해도 충족'
    : 'budget 충족 — 같은 CPU co-runner 대기를 모두 더해도 충족'
  if (v.tier === 'miss') return 'budget 미충족 (자체 실행시간 기준)'
  if (v.tier === 'unchecked') return 'budget 충족 (자체 실행시간 기준) — 같은 CPU co-runner 대기는 이 분배에서 검사하지 않음 (상위 목록에서 검증)'
  const who = v.task ? `${v.task}: ` : ''
  const wait = v.wait_ms !== undefined ? ` (co-runner ${fmt(v.wait_ms, 2)} ms)` : ''
  if (v.tier === 'wait_miss') return `대기 미충족 — 자체 실행시간으로는 충족, 스케줄링 클래스 · 우선순위(task_policy)로 같은 CPU 대기를 더하면 ${who}slack ${fmt(v.shared_ms!, 2)} ms${wait}. `
    + '우선순위 상향(RT) 또는 co-runner 분리 검토'
  return `조건부 충족 — 자체 실행시간으로는 충족, 같은 CPU co-runner를 모두 기다리면 ${who}slack ${fmt(v.shared_ms!, 2)} ms${wait}. `
    + '우선순위 미지정: scheduler.task_policy에 sched_class · rt_priority / nice를 넣으면 충족 / 대기 미충족으로 판정'
}
/** "FIFO 2" / "RR 5" / "nice −10" / "nice 0" */
export function schedText(p: TaskSched | undefined): string | null {
  if (!p) return null
  return p.sched_class === 'normal' ? `nice ${(p.nice ?? 0) < 0 ? '−' : ''}${Math.abs(p.nice ?? 0)}` : `${p.sched_class.toUpperCase()} ${p.rt_priority ?? 1}`
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
