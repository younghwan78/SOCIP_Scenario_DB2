import { useState } from 'react'
import { Card } from './TimingCharts'
import { fmt } from '../lib/timingBudget'
import { describeChange, evidenceLabel, type ChangeKindMeta, type WhatIfSettings, type WhatIfChange, type WhatIfCoverage, type WhatIfResult, type WhatIfScope, type WhatIfTargets } from '../lib/scenarioWhatIf'
import { experimentHref, updateExperimentContext, useExperimentContext, type ExperimentCandidate } from '../lib/experimentContext'
import './WhatIfWorkbench.css'

export function ResultState({ dirty, condition }: { dirty: boolean; condition: string }) {
  return <div className={`wi-result-state ${dirty ? 'is-stale' : ''}`} role={dirty ? 'status' : undefined}>
    <strong>{dirty ? '이전 조건 결과 · 재계산 필요' : '계산한 조건'}</strong><span>{condition || '기준 조건'}</span>
    {dirty && <span>현재 편집 중인 조건과 다릅니다. “답 보기”로 다시 계산하세요.</span>}
  </div>
}
export function PowerCoverage({ coverage, sensorPower }: { coverage: WhatIfCoverage; sensorPower?: number | null }) {
  return <div className="wi-power-scope" aria-label="전력 비교 범위">
    <strong>{coverage.complete ? '모델 범위 충족' : '부분 모델'} · {coverage.scope}</strong>
    <span>센서 전력: {sensorPower == null ? '미확정' : `${fmt(sensorPower, 2)} mW`}</span>
    <span>제외: {coverage.excluded_components.join(' · ') || '없음'}{coverage.missing_components.length ? ` · 누락: ${coverage.missing_components.join(' · ')}` : ''}</span>
    <span>실측 정확도·화질·배선 호환성은 별도 검증이 필요합니다.</span>
  </div>
}
export function BaselineCard({ targets, scope, result }: { targets?: WhatIfTargets; scope: WhatIfScope; result?: WhatIfResult | null }) {
  const lineage = targets?.model_lineage ?? result?.model_lineage
  const sensors = targets?.change_kinds?.find((k) => k.target === 'sensor_mode')?.choices ?? []
  const basis = lineage?.basis_code ?? lineage?.basis_ref ?? lineage?.config_profile_ref ?? '서버가 선택한 과제 모델 기준'
  const coverage = targets?.baseline?.coverage ?? result?.baseline.coverage
  return <section className="wi-baseline" aria-label="고정된 실험 기준">
    <div><strong>기준 · {scope.variant_id}</strong><span>{scope.project_ref} / {scope.scenario_id}</span></div>
    <div><strong>{targets?.fps ?? '—'} fps</strong><span>{targets?.anchors.filter((a) => a.kind === 'output').map((a) => `${a.role ?? a.id} ${a.size.join('×')}`).join(' · ') || '최종 출력은 시나리오 정의 유지'}</span></div>
    <div><strong>모델 기준</strong><span>{String(basis)}</span><span>{targets?.capability?.readiness ?? '검증 범위 확인 필요'} · {targets?.capability?.soc_profile ?? ''}</span></div>
    {sensors.map((s) => <div key={s.id}><strong>{s.sensor ?? s.id} · {s.size?.join('×')}</strong><span>{s.mode ?? '모드 미기록'}{s.readout_ms != null ? ` · readout ${s.readout_ms} ms` : ''}</span></div>)}
    {coverage && <PowerCoverage coverage={coverage} sensorPower={targets?.baseline?.metrics.sensor_power_mw} />}
    <details><summary>기준 식별값·모델 버전·변경 정책</summary><p>모든 후보는 기준 입력과 모델 버전을 확인한 뒤 계산합니다. 기준이 바뀌면 갱신 후 다시 계산해야 합니다.</p><code>{targets?.baseline_hash ?? '기준 불러오는 중…'}</code>{targets?.analysis_hash && <p><code>{targets.analysis_hash}</code></p>}<dl className="wi-lineage">{Object.entries(lineage ?? {}).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—')}</dd></div>)}</dl></details>
  </section>
}
export function ImpactPreview({ changes, kinds }: { changes: WhatIfChange[]; kinds: ChangeKindMeta[] }) {
  if (!changes.length) return null
  return <details className="wi-impact" open><summary>계산 전 영향 미리보기 · 변경 {changes.length}개</summary>
    <ul>{changes.map((change, index) => {
      const kind = kinds.find((k) => k.target === change.target), row = kind?.selector ? kind.choices.find((c) => c.id === change[kind.selector!]) : undefined
      const option = row?.options?.find((o) => o.id === change.option)
      return <li key={index}><strong>{describeChange(change)}</strong>
        {row?.downstream?.length ? <span>영향 IP: {row.downstream.join(' → ')}</span> : null}
        {row?.affected_buffers?.length ? <span>영향 buffer: {row.affected_buffers.join(', ')}</span> : null}
        {change.target === 'sensor_mode' || change.target === 'sensor_binding' ? <span>센서 readout·입력과 후단 크기 재평가 · 최종 출력과 배선 호환성 확인 필요</span> : null}
        <span>근거: {evidenceLabel(option?.evidence ?? row?.evidence)}{option?.reason ? ` · ${option.reason}` : ''}</span></li>
    })}</ul><p className="faint">변경되지 않은 SW 시간과 bitstream bitrate는 기준 가정을 유지합니다. 실제 영향·제약 판정은 서버 계산 결과에서 확인하세요.</p>
  </details>
}
export function CandidateBench({ scope, result, targets, settings, dirty, onLoad }: { scope: WhatIfScope; result?: WhatIfResult | null; targets?: WhatIfTargets; settings: WhatIfSettings; dirty: boolean; onLoad: (candidate: ExperimentCandidate) => void }) {
  const context = useExperimentContext(scope), [name, setName] = useState('')
  const candidates = context?.candidates ?? []
  const pin = () => {
    if (!result || dirty) return
    const candidate: ExperimentCandidate = { id: result.condition_hash, condition_hash: result.condition_hash, baseline_hash: result.baseline_hash, analysis_hash: result.analysis_hash ?? targets?.analysis_hash,
      title: name.trim() || `후보 ${String.fromCharCode(65 + candidates.length)}`, changes: result.normalized_condition.changes,
      config: settings.config, options: settings.options, comparison: settings.comparison, basis_ref: settings.basis_ref ?? (typeof result.model_lineage.basis_ref === 'string' ? result.model_lineage.basis_ref : undefined),
      metrics: result.candidate.metrics, baseline_metrics: result.baseline.metrics, coverage: result.candidate.coverage,
      iq_required: result.iq_required ?? [], created_at: new Date().toISOString() }
    updateExperimentContext(scope, { candidates: [...candidates.filter((c) => c.id !== candidate.id), candidate].slice(-5), active_candidate_id: candidate.id })
    setName('')
  }
  return <Card id="wi-candidates" title="후보 비교" note="최대 5개 · 계산 당시 조건과 기준을 보존 · 브라우저 탭 안에 임시 보관" defaultWide>
    <div className="toolbar"><label>후보 이름 <input className="input" aria-label="후보 이름" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="예: YUVSC FHD" /></label><button className="btn" disabled={!result || dirty} onClick={pin}>현재 결과를 후보로 담기</button></div>
    {!candidates.length ? <p className="faint">조건을 계산한 뒤 후보로 담으세요. 다른 설정을 계산해 같은 기준에서 나란히 비교할 수 있습니다.</p> : <div className="table-x"><table className="tb-mini-table wi-candidate-table"><thead><tr><th>후보·조건</th><th>기준 대비 모델 ΔmW</th><th>모델 mW</th><th>BW MB/s</th><th>Latency ms</th><th>FPS</th><th>판정·검증</th><th>동작</th></tr></thead><tbody>{candidates.map((candidate) => {
      const compatible = candidate.baseline_hash === (targets?.baseline_hash ?? result?.baseline_hash ?? context?.baseline_hash) && (!candidate.analysis_hash || !targets?.analysis_hash || candidate.analysis_hash === targets.analysis_hash)
      return <tr key={candidate.id}><th>{candidate.title}<small>{candidate.changes.map(describeChange).join(' · ')}</small><small>{candidate.comparison === 'fixed_opp' ? '기준 OPP 고정' : '변경 후 OPP 재선택'}</small></th>
        <td>{compatible ? fmt(candidate.metrics.modeled_power_mw - candidate.baseline_metrics.modeled_power_mw, 2) : '기준 다름'}</td><td>{fmt(candidate.metrics.modeled_power_mw, 2)}</td><td>{fmt(candidate.metrics.bw_mbs, 0)}</td><td>{fmt(candidate.metrics.latency_ms, 2)}</td><td>{fmt(candidate.metrics.fps, 0)}</td>
        <td>{candidate.metrics.feasible ? 'Timing 충족' : 'Timing 미달'}<small>{candidate.coverage.complete ? '모델 범위 충족' : '부분 모델'} · {candidate.iq_required.length ? 'IQ 미검증' : 'IQ 별도 확인'}{!compatible ? ' · 현재 기준으로 재계산 필요' : ''}</small></td>
        <td><button className="btn tb-mini" onClick={() => { updateExperimentContext(scope, { active_candidate_id: candidate.id }); onLoad(candidate) }}>조건 불러오기</button>{candidate.saved_experiment_id && <a href={experimentHref('whatif', scope, candidate.saved_experiment_id)}>저장 기록</a>}
          <button className="btn tb-mini" aria-label={`${candidate.title} 비교에서 제거`} onClick={() => updateExperimentContext(scope, { candidates: candidates.filter((c) => c.id !== candidate.id), active_candidate_id: context?.active_candidate_id === candidate.id ? undefined : context?.active_candidate_id })}>제거</button></td></tr>
    })}</tbody></table></div>}
  </Card>
}
