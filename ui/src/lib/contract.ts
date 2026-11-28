import type { CatalogItem, ScenarioContract } from './api'

/** Sink kinds the engine does not judge by frame interval (sim/timing_budget.py: audio, file). */
export const UNJUDGED_SINK_KINDS = new Set(['audio', 'file'])

/** X-15: small badges of what a scenario declares for judgement and which results it has. */
export function contractBadges(c: ScenarioContract | null | undefined): { key: string; text: string; title: string }[] {
  if (!c) return []
  const out: { key: string; text: string; title: string }[] = []
  if (c.rate) out.push({ key: 'rate', text: `rate: ${c.rate}`, title: '판정 주기 출처 (judgement.rate) — 없으면 variant의 target fps' })
  if (c.sinks.length) {
    const kinds = [...new Set(c.sinks.map((s) => s.kind))]
    out.push({ key: 'sink', text: `sink: ${kinds.join(' · ')}`, title: `판정 계약 sink: ${c.sinks.map((s) => `${s.node} (${s.kind})`).join(', ')}${kinds.some((k) => UNJUDGED_SINK_KINDS.has(k)) ? '\naudio · file sink는 frame 간격으로 판정하지 않음' : ''}` })
  }
  if (c.kpis.length) out.push({ key: 'kpi', text: `KPI ${c.kpis.length}`, title: `선언 KPI: ${c.kpis.join(', ')} · 목표 ${c.targets}개` })
  if (c.jobs.length) out.push({ key: 'job', text: `job ${c.jobs.length}`, title: `event job: ${c.jobs.join(', ')} — Timing Budget의 Event job 카드` })
  if (c.subsystems.length) out.push({ key: 'ss', text: `subsystem ${c.subsystems.map((s) => s.toUpperCase()).join(' · ')}`, title: 'mcps-v1 subsystem node — Timing Budget의 Subsystem 카드' })
  return out
}

/** X-06: why a scenario has no registered prediction, from its contract. ``registrable`` = nothing in the
 * contract keeps it out (not registered yet); the others name what decides it and where to look. */
export type RegistrationPath = 'registrable' | 'event_job' | 'not_judged'
export function registrationPath(c: ScenarioContract | null | undefined): { kind: RegistrationPath; text: string } {
  if (c?.jobs.length) return { kind: 'event_job', text: 'event job — job KPI는 탐색 · 예측 등록에 들어가지 않음, Timing Budget에서 확인' }
  if (c && c.sinks.length && c.sinks.every((s) => UNJUDGED_SINK_KINDS.has(s.kind)))
    return { kind: 'not_judged', text: '출력이 audio · file sink뿐 — timing 판정 미지원이면 예측 등록 대상 아님 (KPI는 Timing Budget에서 확인)' }
  // no contract-level reason: registration depends on the timing verdict (OK · Clock ↑ registers; 판정 미지원 / Fail do not)
  return { kind: 'registrable', text: '미등록 — 등록 가능 여부는 Timing 판정(OK · Clock ↑만 등록)에 따름' }
}

export function catalogContract(catalog: CatalogItem[] | undefined, scenarioId: string): ScenarioContract | null {
  return (catalog ?? []).find((c) => c.scenario_id === scenarioId)?.contract ?? null
}
