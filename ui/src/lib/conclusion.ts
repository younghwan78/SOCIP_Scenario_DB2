import { caseDelta, coverageOf, variantSpecState, type ExpCase, type VariantResult } from './archExplore'
import { fmt } from './timingBudget'

/** What a variant of an exploration run concludes: the case the default registration takes, its verdict,
 * what it changes against the baseline and the (at most three) things to be careful about (U-03). */
export interface Conclusion {
  /** the case "등록" registers without a case_key — the server rule, never re-derived differently */
  target: ExpCase | null
  /** auto:min-power · auto:min-power-iq (project policy iq_keep) */
  rule: 'auto:min-power' | 'auto:min-power-iq'
  targetLabel: string
  verdict: 'ok' | 'fail' | 'not_applicable'
  reasons: string[]
  /** the default registration would be accepted: spec ok, an eligible target that did not fail re-simulation */
  registrable: boolean
  delta: { total_mw: number; total_pct: number | null; bw_mbs: number } | null
  /** objective-order recommendation when it is not the registered case (registered by picking it) */
  objective: { case: ExpCase; delta_mw: number } | null
  cautions: string[]
  /** cautions beyond the three shown */
  more: number
}

const MAX_CAUTIONS = 3

/** The case the server registers by default (``promote`` without ``case_key``): the IQ-keeping optimum under
 * the project policy ``iq_keep``, else the lowest-power case — which, with an objective order, is
 * ``min_power_case`` and not the recommendation. */
export function defaultCase(v: VariantResult, iqKeep: boolean): ExpCase | null {
  if (iqKeep) return v.tiers?.keep?.best ?? null
  return v.objectives ? v.min_power_case ?? null : v.recommended
}

export function lowestPowerCase(v: VariantResult): ExpCase | null {
  return v.objectives ? v.min_power_case ?? null : v.recommended
}

export function conclusion(v: VariantResult, iqKeep: boolean): Conclusion {
  const target = defaultCase(v, iqKeep)
  const cautions: string[] = []
  const verified = target?.verified
  // the variant verdict follows the recommendation; the registered case can be another one (objective order,
  // iq_keep) whose own re-simulation failed — the server refuses to register it, so the decision fails too
  const targetFailed = !!verified && !verified.ok
  const spec = variantSpecState(v)
  const verdict = spec === 'ok' && targetFailed ? 'fail' : spec
  const reasons = spec === 'fail' ? v.spec_reasons
    : targetFailed ? [`기본 등록 조합 재시뮬레이션 검증 실패 — ${(verified!.reasons ?? ['mismatch']).slice(0, 1).join('')}`] : []
  const coverage = coverageOf(v)
  if (coverage === 'partial') {
    const ips = v.coverage?.zero_power_ips ?? []
    cautions.push(`부분 모델 — 전력 미모델 IP ${ips.length}개 (${ips.slice(0, 3).join(', ')}${ips.length > 3 ? ' …' : ''}), total은 하한`)
  } else if (coverage === 'none') {
    cautions.push('전력 모델 없음 — IP 전력이 모델되지 않아 total은 CPU · BW 합만')
  } else if (coverage === undefined) {
    cautions.push('전력 모델 범위 미확인 (coverage 기록 이전 결과)')
  }
  if (v.status?.power_budget_status === 'unknown') cautions.push('power budget 판정 불가 (전력 모델 불완전)')
  if (target?.lossy && target.compression.length) cautions.push('lossy 압축 포함 — IQ 평가 필요')
  if (target?.assumed_ratio && target.compression.length) cautions.push('가정 compression ratio 사용 — catalog에 없는 ratio')
  if (target?.dvfs_raise) cautions.push(`DVFS를 해석 level보다 ${target.dvfs_raise} domain 올린 조합`)
  const rec = v.recommended
  const objective = v.objectives && rec && target && rec.key !== target.key
    ? { case: rec, delta_mw: rec.total_mw - target.total_mw } : null
  if (objective) cautions.push(`추천 기준(${v.objectives!.order.join(' → ')})의 추천은 다른 조합 (${objective.delta_mw >= 0 ? '+' : ''}${fmt(objective.delta_mw, 1)} mW) — 필요하면 그 조합을 골라 등록`)
  const d = target ? caseDelta(target, v.baseline) : null
  return {
    target, rule: iqKeep ? 'auto:min-power-iq' : 'auto:min-power',
    targetLabel: iqKeep ? '화질 유지 최저 power (과제 기준 iq_keep)' : '최저 power',
    verdict, reasons, registrable: verdict === 'ok' && !!target?.eligible,
    delta: d ? { total_mw: d.total, total_pct: v.baseline.total_mw ? (100 * d.total) / v.baseline.total_mw : null, bw_mbs: d.bw_mbs } : null,
    objective, cautions: cautions.slice(0, MAX_CAUTIONS), more: Math.max(0, cautions.length - MAX_CAUTIONS),
  }
}
