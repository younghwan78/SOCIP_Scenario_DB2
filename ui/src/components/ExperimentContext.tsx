import type { Page } from '../lib/route'
import type { WhatIfScope } from '../lib/scenarioWhatIf'
import { experimentHref, useExperimentContext } from '../lib/experimentContext'
import './ExperimentContext.css'

const LINKS: [Page, string][] = [['whatif', '조건·후보'], ['pipeline', 'Pipeline'], ['timing', 'Timing'], ['compare', '비교'], ['calibration', '실측 검증'], ['reports', '보고서']]
export function ExperimentContextBar({ scope, page }: { scope: WhatIfScope; page?: Page }) {
  const experiment = useExperimentContext(scope)
  if (!scope.variant_id || !experiment || (!experiment.changes.length && !experiment.candidates.length)) return null
  const candidate = experiment.candidates.find((c) => c.id === experiment.active_candidate_id)
  return <aside className="experiment-context" aria-label="진행 중인 실험">
    <div><strong>실험 기준 · {scope.variant_id}</strong><span>{experiment.basis_label ?? '계산 시 모델 기준 확인'} · 변경 {experiment.changes.length}개 · 후보 {experiment.candidates.length}개</span>
      {candidate && <span>선택 후보: {candidate.title} · 모델 전력 {candidate.metrics.modeled_power_mw.toFixed(1)} mW{candidate.coverage.complete ? '' : ' · 부분 모델'}</span>}</div>
    <nav aria-label="실험 분석 이동">{LINKS.map(([target, label]) => <a key={target} aria-current={target === page ? 'page' : undefined} href={experimentHref(target, scope, candidate?.saved_experiment_id)}>{label}</a>)}</nav>
    {page !== 'whatif' && <small>이 페이지의 기존 계산은 별도 조건일 수 있습니다. 후보 수치는 What-If의 고정된 계산 결과를 확인하세요.</small>}
  </aside>
}
