import { useEffect, useMemo, useRef, useState } from 'react'
import { Card } from './TimingCharts'
import { PowerCoverage, ResultState } from './WhatIfWorkbench'
import { fmt } from '../lib/timingBudget'
import { readExperimentContext, updateExperimentContext } from '../lib/experimentContext'
import { describeChange, kindsOf, sweepValues, whatIfApi, type ChangeKindMeta, type PreviewRequest, type WhatIfSettings, type SweepConstraints, type SweepJob, type SweepRequest, type SweepResult, type WhatIfChange, type WhatIfScope, type WhatIfTargets } from '../lib/scenarioWhatIf'

interface AxisDraft { index: number; identity: string; values: string }
const conditionIdentity = (change: WhatIfChange) => JSON.stringify([change.target, change.anchor_id, change.node_id, change.stream_id, change.buffer_id, change.domain, change.param])
const finished = (job: SweepJob | null) => !job || !['pending', 'queued', 'running'].includes(job.status)
const statusLabels: Record<string, string> = { pending: '대기', queued: '대기', running: '계산 중', completed: '완료', cancelled: '중단', interrupted: '중단됨 · 재개 가능', failed: '오류' }
const errorText = (e: unknown) => e instanceof Error ? e.message : String(e)
function valueHint(kind?: ChangeKindMeta): string {
  return kind?.shape === 'size' ? '1920×1080, 2560×1440, 3840×2160' : kind?.shape === 'level' ? 'L5, L4, L3' : '15, 30, 60'
}
export function WhatIfSweep({ scope, targets, changes, settings, onLoad }: { scope: WhatIfScope; targets: WhatIfTargets; changes: WhatIfChange[]; settings: WhatIfSettings; onLoad: (request: PreviewRequest) => void }) {
  const kinds = useMemo(() => kindsOf(targets), [targets])
  const [axes, setAxes] = useState<AxisDraft[]>([])
  const [constraints, setConstraints] = useState<SweepConstraints>({ allow_iq_required: false })
  const [comparison, setComparison] = useState<'retune' | 'fixed_opp'>('retune')
  const [jobId, setJobId] = useState<string | null>(() => readExperimentContext(scope)?.job_id ?? null)
  const [job, setJob] = useState<SweepJob | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [runSignature, setRunSignature] = useState<string | null>(null)
  const [eligibleOnly, setEligibleOnly] = useState(false)
  const [pollTick, setPollTick] = useState(0)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const built = useMemo(() => {
    try {
      if (!axes.length) return { body: null, error: '현재 조건에서 1–4개 항목을 골라 탐색 값을 지정하세요.', count: 0 }
      if (new Set(axes.map((axis) => axis.index)).size !== axes.length) throw new Error('같은 조건을 두 탐색 축에 중복 지정할 수 없습니다.')
      const parsed = axes.map((axis) => {
        const change = changes[axis.index], kind = kinds.find((k) => k.target === change?.target)
        if (!change || !kind || axis.identity !== conditionIdentity(change)) throw new Error('원래 조건이 바뀌었습니다. 탐색 항목을 다시 선택하세요.')
        return { label: kind.label + (kind.selector ? ` · ${change[kind.selector] ?? ''}` : ''), values: sweepValues(change, kind, axis.values) }
      })
      const count = parsed.reduce((value, axis) => value * axis.values.length, 1)
      if (count > 256) throw new Error(`전체 ${count}개 조합입니다. 256개 이하로 줄이세요.`)
      for (const [key, value] of Object.entries(constraints)) if (key !== 'allow_iq_required' && value != null && (typeof value !== 'number' || !Number.isFinite(value) || value < 0)) throw new Error('제약 조건은 0 이상의 유한한 숫자여야 합니다.')
      const body: SweepRequest = { ...scope, ...settings, expected_baseline_hash: targets.baseline_hash, ...(targets.analysis_hash ? { expected_analysis_hash: targets.analysis_hash } : {}),
        changes: changes.filter((_, index) => !axes.some((axis) => axis.index === index)), axes: parsed, constraints, comparison }
      return { body, count, error: null }
    } catch (e) { return { body: null, count: 0, error: errorText(e) } }
  }, [axes, changes, kinds, settings, targets.baseline_hash, targets.analysis_hash, constraints, comparison, scope.project_ref, scope.scenario_id, scope.variant_id])
  const signature = built.body ? JSON.stringify(built.body) : null
  const result = job?.result
  const outdated = !!result && (result.baseline_hash !== targets.baseline_hash || (!!targets.analysis_hash && result.analysis_hash !== targets.analysis_hash) || (!!runSignature && signature !== runSignature))
  useEffect(() => {
    if (!jobId) return
    let live = true, timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try {
        const value = await whatIfApi.job(jobId)
        if (!live) return
        setJob(value)
        if (!finished(value)) timer = setTimeout(() => { void poll() }, 1200)
      } catch (e) { if (live) setMessage(`탐색 상태를 확인하지 못했습니다: ${errorText(e)}. 작업 ID ${jobId}`) }
    }
    void poll()
    return () => { live = false; if (timer) clearTimeout(timer) }
  }, [jobId, job?.status, pollTick])
  const start = async () => {
    if (!built.body || busy) return
    setBusy(true); setMessage('')
    try {
      const next = await whatIfApi.startJob(built.body)
      if (!alive.current) return
      setJob(next); setJobId(next.id); setRunSignature(signature)
      updateExperimentContext(scope, { job_id: next.id })
    } catch (e) { if (alive.current) setMessage(errorText(e)) }
    finally { if (alive.current) setBusy(false) }
  }
  const control = async (action: 'cancel' | 'resume') => {
    if (!jobId || busy) return
    setBusy(true); setMessage('')
    try { const next = await (action === 'cancel' ? whatIfApi.cancelJob(jobId) : whatIfApi.resumeJob(jobId)); if (alive.current) setJob(next) }
    catch (e) { if (alive.current) setMessage(errorText(e)) }
    finally { if (alive.current) setBusy(false) }
  }
  const editAxis = (at: number, patch: Partial<AxisDraft>) => setAxes((old) => old.map((axis, index) => index === at ? { ...axis, ...patch } : axis))
  return <Card id="wi-sweep" title="값 범위 탐색 · 성능과 전력 비교" note="센서·mode·크기 등 최대 4개 축 / 256개 조합 · 서버에 진행 상태 저장" defaultWide>
    <p className="faint">위에서 비교할 조건을 만든 뒤 여러 값을 지정하세요. 선택하지 않은 조건은 모든 후보에 동일하게 적용합니다.</p>
    <div className="toolbar"><button className="btn" disabled={!changes.length || axes.length >= Math.min(4, changes.length)} onClick={() => { const index = changes.findIndex((_, index) => !axes.some((axis) => axis.index === index)); setAxes([...axes, { index, identity: conditionIdentity(changes[index]), values: '' }]) }}>탐색 항목 추가</button>
      <label>전력 비교 방식 <select aria-label="전력 비교 방식" value={comparison} onChange={(e) => setComparison(e.target.value as 'retune' | 'fixed_opp')}><option value="retune">변경 후 OPP 재선택</option><option value="fixed_opp">기준 OPP 고정 · 변경 자체 효과</option></select></label></div>
    <div className="wi-sweep-axes">{axes.map((axis, at) => {
      const change = changes[axis.index], kind = kinds.find((k) => k.target === change?.target)
      const row = kind?.selector && change ? kind.choices.find((choice) => choice.id === change[kind.selector!]) : undefined
      const selected = axis.values.split('\n').filter(Boolean)
      return <fieldset className="wi-sweep-axis" key={at}><legend>탐색 축 {at + 1}</legend><label>조건<select aria-label={`탐색 축 ${at + 1} 조건`} value={change && conditionIdentity(change) === axis.identity ? axis.index : ''} onChange={(e) => { if (e.target.value !== '') { const index = Number(e.target.value); editAxis(at, { index, identity: conditionIdentity(changes[index]), values: '' }) } }}><option value="" disabled>조건 다시 선택</option>{changes.map((item, index) => <option key={index} value={index}>{describeChange(item)}</option>)}</select></label>
        {kind?.shape === 'choice' ? <label>비교할 값 (2–12개)<select multiple size={Math.min(7, row?.options?.length ?? 2)} aria-label={`탐색 축 ${at + 1} 값`} value={selected} onChange={(e) => editAxis(at, { values: [...e.target.selectedOptions].map((option) => option.value).join('\n') })}>{row?.options?.map((option) => <option key={option.id} value={option.id} disabled={option.supported === false}>{option.label ?? option.id}{option.mode ? ` · ${option.mode}` : ''}</option>)}</select></label>
          : <label>비교할 값 (쉼표·줄바꿈 구분)<textarea className="input" aria-label={`탐색 축 ${at + 1} 값`} rows={2} value={axis.values} onChange={(e) => editAxis(at, { values: e.target.value })} placeholder={valueHint(kind)} /></label>}
        <button className="btn tb-mini" onClick={() => setAxes(axes.filter((_, index) => index !== at))}>탐색 축 제거</button></fieldset>
    })}</div>
    <div className="wi-sweep-constraints">{([{ key: 'max_power_mw', label: '모델 전력 상한 mW' }, { key: 'max_bw_mbs', label: 'BW 상한 MB/s' }, { key: 'max_latency_ms', label: 'Latency 상한 ms' }, { key: 'min_slack_ms', label: '최소 여유 ms' }] as const).map(({ key, label }) => <label key={key}>{label}<input className="input" type="number" min={0} aria-label={label} value={constraints[key] ?? ''} onChange={(e) => setConstraints({ ...constraints, [key]: e.target.value === '' ? undefined : Number(e.target.value) })} /></label>)}
      <label><input type="checkbox" checked={constraints.allow_iq_required} onChange={(e) => setConstraints({ ...constraints, allow_iq_required: e.target.checked })} /> IQ 미검증 후보도 비교에 포함</label></div>
    {built.error && <p className="faint">{built.error}</p>}
    <button className="btn primary" disabled={!built.body || busy || !finished(job)} onClick={() => { void start() }}>범위 탐색 실행{built.count ? ` (${built.count}개)` : ''}</button>
    {jobId && <div className="wi-job-status" role="status"><strong>{job ? statusLabels[job.status] ?? job.status : '작업 확인 중'}</strong><progress aria-label="범위 탐색 진행률" max={job?.total_cases || 1} value={job?.completed_cases ?? 0} /><span>{job?.completed_cases ?? 0} / {job?.total_cases ?? '—'}개</span>
      {!finished(job) && <button className="btn" disabled={busy || job?.cancel_requested} onClick={() => { void control('cancel') }}>{job?.cancel_requested ? '중단 요청됨' : '탐색 중단'}</button>}{job?.resumable && finished(job) && <button className="btn" disabled={busy} onClick={() => { void control('resume') }}>남은 계산 재개</button>}<button className="btn tb-mini" disabled={busy} onClick={() => { setMessage(''); setPollTick((n) => n + 1) }}>상태 다시 확인</button><small>작업 {jobId}</small></div>}
    {(message || job?.error) && <p className="err" role="status">{message || job?.error}</p>}
    {result && <><ResultState dirty={outdated} condition={`${result.completed_cases}/${result.total_cases}개 조합 · ${result.comparison === 'fixed_opp' ? '기준 OPP 고정' : '변경 후 OPP 재선택'} · 기준 ${result.baseline_hash.slice(0, 10)}`} />
      {result.constraints && <p className="faint">계산 당시 제약: 모델 전력 ≤ {result.constraints.max_power_mw ?? '제한 없음'} mW · BW ≤ {result.constraints.max_bw_mbs ?? '제한 없음'} MB/s · Latency ≤ {result.constraints.max_latency_ms ?? '제한 없음'} ms · 최소 여유 ≥ {result.constraints.min_slack_ms ?? '제한 없음'} ms · IQ 미검증 {result.constraints.allow_iq_required ? '포함' : '제외'}</p>}
      <PowerCoverage coverage={result.baseline.coverage} sensorPower={result.baseline.metrics.sensor_power_mw} />
      <SweepPlot result={result} /><label><input type="checkbox" checked={eligibleOnly} onChange={(e) => setEligibleOnly(e.target.checked)} /> 제약을 만족하는 후보만</label>
      <div className="table-x"><table className="tb-mini-table wi-candidate-table"><thead><tr><th>후보</th><th>모델 ΔmW</th><th>BW MB/s</th><th>Latency ms</th><th>최소 여유 ms</th><th>판정·제외 사유</th><th /></tr></thead><tbody>{result.rows.filter((row) => !eligibleOnly || row.eligible).map((row) => <tr key={row.id} className={result.pareto_ids.includes(row.id) ? 'wi-sweep-selected' : ''}><th>{result.best_id === row.id ? '★ ' : result.best_trade_id === row.id ? '◆ ' : ''}{row.label}<small>{row.changes.map(describeChange).join(' · ')}</small></th><td>{fmt(row.delta?.modeled_power_mw, 2)}</td><td>{fmt(row.metrics?.bw_mbs, 0)}</td><td>{fmt(row.latency_ms, 2)}</td><td>{fmt(row.min_slack_ms, 2)}</td><td>{row.eligible ? '제약 충족' : '제약 미충족'}{result.pareto_ids.includes(row.id) ? ' · 절충 후보' : ''}<small>{row.reasons.join(' · ')}{row.iq_required.length ? ' · IQ 미검증' : ''}</small></td><td><button className="btn tb-mini" disabled={!row.metrics || outdated} onClick={() => onLoad(row.preview_request ?? { ...scope, ...settings, changes: row.changes, expected_baseline_hash: result.baseline_hash })}>상세 조건 불러오기</button></td></tr>)}</tbody></table></div>
      <p className="faint">★ 제약을 만족하는 최저 모델 전력{result.best_trade_id ? " · ◆ IQ 평가 필요 후보를 허용하면 더 낮은 전력 (기본 제외)" : ""} · 절충 후보는 전력과 성능을 함께 비교하세요. Timing 충족은 실측·IQ 검증 완료를 뜻하지 않습니다.</p>{result.assumptions.map((note) => <p className="faint" key={note}>{note}</p>)}</>}
  </Card>
}
function SweepPlot({ result }: { result: SweepResult }) {
  const rows = result.rows.filter((row) => row.metrics && Number.isFinite(row.metrics.bw_mbs) && Number.isFinite(row.metrics.modeled_power_mw))
  if (rows.length < 2) return null
  const xs = rows.map((row) => row.metrics!.bw_mbs), ys = rows.map((row) => row.metrics!.modeled_power_mw)
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys)
  return <figure><figcaption>BW와 모델 전력 · 초록은 제약을 만족하는 절충 후보, 회색은 제약 미충족</figcaption><svg viewBox="0 0 650 260" className="wi-sweep-chart" aria-hidden="true"><path d="M60 15V220H630" fill="none" stroke="#8c9d95" /><text x="8" y="15">mW</text><text x="520" y="250">BW MB/s</text><text x="58" y="242">{fmt(minX, 0)}</text><text x="580" y="242">{fmt(maxX, 0)}</text><text x="8" y="30">{fmt(maxY, 0)}</text><text x="8" y="220">{fmt(minY, 0)}</text>{rows.map((row) => <circle key={row.id} cx={70 + (row.metrics!.bw_mbs - minX) / (maxX - minX || 1) * 535} cy={205 - (row.metrics!.modeled_power_mw - minY) / (maxY - minY || 1) * 175} r={result.pareto_ids.includes(row.id) ? 6 : 4} fill={!row.eligible ? '#aaa' : result.pareto_ids.includes(row.id) ? '#23856d' : '#487caf'}><title>{row.label}: {fmt(row.metrics!.modeled_power_mw, 1)} mW / {fmt(row.metrics!.bw_mbs, 0)} MB/s</title></circle>)}</svg></figure>
}
