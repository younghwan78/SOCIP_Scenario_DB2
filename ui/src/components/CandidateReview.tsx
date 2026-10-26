import { experimentHref, useExperimentContext, type ExperimentContext } from '../lib/experimentContext'
import type { WhatIfScope } from '../lib/scenarioWhatIf'
import { CHANGE_LABELS } from '../lib/scenarioWhatIf'

const value = (n: number | null | undefined) => n == null || !Number.isFinite(n) ? '—' : n.toFixed(1)
const delta = (a: number | null | undefined, b: number | null | undefined) => a == null || b == null ? '—' : `${a - b > 0 ? '+' : ''}${value(a - b)}`

/** Explicit allowlist keeps credentials and unrelated browser state out of local exports. */
export function candidateReviewDocument(context: ExperimentContext) {
  return { schema: 'scenario-experiment-review/v1', status: 'unreviewed_local_snapshot', scope: context.scope,
    baseline_hash: context.baseline_hash ?? null, analysis_hash: context.analysis_hash ?? null, basis_label: context.basis_label ?? null,
    config: context.config ?? {}, options: context.options ?? {},
    notice: 'Model estimates, not measured results. Each delta uses its own frozen baseline. Recalculate before adoption.',
    candidates: context.candidates.map((c) => ({ id: c.id, title: c.title, condition_hash: c.condition_hash, baseline_hash: c.baseline_hash,
      analysis_hash: c.analysis_hash ?? null, config: c.config ?? null, options: c.options ?? null, basis_ref: c.basis_ref ?? null, comparison: c.comparison ?? null,
      changes: c.changes, baseline_metrics: c.baseline_metrics, candidate_metrics: c.metrics, coverage: c.coverage,
      iq_required: c.iq_required, created_at: c.created_at, saved_experiment_id: c.saved_experiment_id ?? null })) }
}

export function CandidateReview({ scope, exportable = false }: { scope: WhatIfScope; exportable?: boolean }) {
  const context = useExperimentContext(scope)
  if (!context?.candidates.length) return null
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(candidateReviewDocument(context), null, 2)], { type: 'application/json;charset=utf-8' }))
    const a = document.createElement('a'); a.href = url; a.download = 'experiment-review.json'; a.click()
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
  return <section className="candidate-review panel" aria-label="실험 후보 비교">
    <div className="toolbar"><b>실험 후보 · 고정 기준 대비</b><span className="badge">{scope.variant_id}</span><span className="grow" />
      <a className="btn" href={experimentHref('whatif', scope)}>조건 수정 · 다시 계산</a>
      {exportable && <button className="btn" onClick={download}>후보 검토 JSON</button>}</div>
    <p className="faint">각 후보의 저장 당시 기준과 비교한 모델 추정치입니다. 아래 등록 예측·보고서의 조건과 별도이며, 후보는 공식 보고서에 자동 포함되지 않습니다.</p>
    <div className="table-x"><table className="tb-mini-table" style={{ width: '100%' }}>
      <thead><tr><th>후보 · 조건</th><th>기준 → 후보 mW</th><th>Δ mW</th><th>Δ BW MB/s</th><th>Δ latency ms</th><th>성능 · 근거</th></tr></thead>
      <tbody>{context.candidates.map((c) => <tr key={c.id}>
        <td><b>{c.title}</b><details><summary>변경 {c.changes.length}개 · 조건 {c.condition_hash.slice(0, 8)}</summary>
          <ul>{c.changes.map((change, i) => <li key={i}>{CHANGE_LABELS[change.target] ?? change.target} · {JSON.stringify(change)}</li>)}</ul>
          <span className="mono">기준 {c.baseline_hash.slice(0, 12)}</span></details></td>
        <td className="mono">{value(c.baseline_metrics.modeled_power_mw)} → {value(c.metrics.modeled_power_mw)}</td>
        <td className="mono">{delta(c.metrics.modeled_power_mw, c.baseline_metrics.modeled_power_mw)}</td>
        <td className="mono">{delta(c.metrics.bw_mbs, c.baseline_metrics.bw_mbs)}</td>
        <td className="mono">{delta(c.metrics.latency_ms, c.baseline_metrics.latency_ms)}</td>
        <td><span className={`badge ${c.metrics.feasible ? 'v-ok' : 'v-fail'}`}>{c.metrics.feasible ? '성능 충족' : '성능 미충족'}</span>
          {!c.coverage.complete && <span className="badge v-warn" title={c.coverage.missing_components.join(', ')}>일부 power만 모델링</span>}
          {c.iq_required.length > 0 && <span className="badge v-warn">IQ 검증 필요</span>}
          {((context.baseline_hash && c.baseline_hash !== context.baseline_hash) || (context.analysis_hash && c.analysis_hash !== context.analysis_hash)) && <span className="badge v-warn">다른 기준 · 재계산 필요</span>}</td>
      </tr>)}</tbody></table></div>
  </section>
}

/** Scope-bound entry and last frozen result for matrix/fleet regression triage. */
export function ExperimentEntry({ scope }: { scope: WhatIfScope }) {
  const context = useExperimentContext(scope)
  const candidate = context?.candidates.find((c) => c.id === context.active_candidate_id) ?? context?.candidates[0]
  return <div className="experiment-entry"><a href={experimentHref('whatif', scope)} onClick={(e) => e.stopPropagation()}>조건 실험 →</a>
    {candidate && <small title={`저장 당시 기준 ${candidate.baseline_hash} 대비 모델 추정치 · ${candidate.created_at}`}>
      저장 Δ {delta(candidate.metrics.modeled_power_mw, candidate.baseline_metrics.modeled_power_mw)} mW · {candidate.metrics.feasible ? '성능 OK' : '성능 FAIL'}
    </small>}</div>
}
