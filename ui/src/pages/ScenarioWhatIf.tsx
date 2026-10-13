import { useEffect, useRef, useState } from 'react'
import type { Ctx } from '../App'
import { ApiError } from '../lib/api'
import { useCredentialKeyId } from '../lib/auth'
import { useAsync } from '../lib/route'
import { fmt } from '../lib/timingBudget'
import { CHANGE_LABELS, clockExplanation, validChange, whatIfApi, type ExperimentDraft, type PreviewRequest, type WhatIfChange, type WhatIfPlan, type WhatIfResult, type WhatIfScope, type WhatIfTargets } from '../lib/scenarioWhatIf'
import { Card } from '../components/TimingCharts'

const EXAMPLES = ['센서 입력은 유지하고 녹화 출력을 FHD로 변경하면 clock과 power는?', 'FPS를 30으로 바꾸면 power는?', 'Change recording output to 1920x1080 and FPS to 30']
const emptyDraft: ExperimentDraft = { title: '', purpose: '', description: '', assumptions: '', conclusion: '', visibility: 'private' }
const date = (value: string) => new Date(value).toLocaleString('ko-KR')
const textError = (error: unknown) => error instanceof ApiError && error.status === 409 ? '기준 입력이 변경되었습니다. 조건 해석 또는 기준 갱신 후 다시 계산하세요.' : error instanceof Error ? error.message : String(error)

export function ScenarioWhatIfPage({ ctx }: { ctx: Ctx }) {
  const credential = useCredentialKeyId()
  if (!ctx.project || !ctx.scenario || !ctx.variant) return <div className="page empty">과제 · scenario · variant를 선택하세요.</div>
  return <WhatIfBody key={`${ctx.project}|${ctx.scenario}|${ctx.variant}|${credential}`} scope={{ project_ref: ctx.project, scenario_id: ctx.scenario, variant_id: ctx.variant }} />
}
function WhatIfBody({ scope }: { scope: WhatIfScope }) {
  const credential = useCredentialKeyId()
  const [tick, setTick] = useState(0)
  const [offset, setOffset] = useState(0)
  const [basisTick, setBasisTick] = useState(0)
  const targetsQ = useAsync(() => whatIfApi.targets(scope), [scope.project_ref, scope.scenario_id, scope.variant_id, basisTick])
  const savedQ = useAsync(() => whatIfApi.experiments(scope, offset), [scope.project_ref, scope.scenario_id, scope.variant_id, offset, tick, credential])
  const [query, setQuery] = useState('')
  const [plan, setPlan] = useState<WhatIfPlan | null>(null)
  const [changes, setChanges] = useState<WhatIfChange[]>([])
  const [result, setResult] = useState<WhatIfResult | null>(null)
  const [request, setRequest] = useState<PreviewRequest | null>(null)
  const [modelSettings, setModelSettings] = useState<Pick<PreviewRequest, 'config' | 'options'>>({})
  const [draft, setDraft] = useState<ExperimentDraft>({ ...emptyDraft })
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [stale, setStale] = useState(false)
  const busyRef = useRef(false)
  const live = useRef(true)
  const generation = useRef(0)
  useEffect(() => { live.current = true; return () => { live.current = false; generation.current++ } }, [])
  const invalidate = () => { generation.current++; setResult(null); setRequest(null); setMessage('') }
  const updateChanges = (next: WhatIfChange[]) => { invalidate(); setChanges(next) }
  const run = async (action: (active: () => boolean) => Promise<void>) => {
    if (busyRef.current) return
    const sequence = generation.current
    busyRef.current = true; setBusy(true); setMessage('')
    const active = () => live.current && generation.current === sequence
    try { await action(active) } catch (error) { if (active()) { setMessage(textError(error)); if (error instanceof ApiError && error.status === 409) { setStale(true); setResult(null); setRequest(null) } } }
    finally { busyRef.current = false; if (live.current) setBusy(false) }
  }
  const interpret = () => run(async (active) => {
    const next = await whatIfApi.plan(scope, query.trim())
    if (active()) { setPlan(next); setChanges(next.changes); setResult(null); setRequest(null); setStale(false) }
  })
  const baselineHash = plan?.baseline_hash ?? targetsQ.data?.baseline_hash
  const preview = () => run(async (active) => {
    if (!baselineHash || stale || !changes.length || !changes.every(validChange)) return
    const body: PreviewRequest = { ...scope, ...modelSettings, changes, expected_baseline_hash: baselineHash }
    const next = await whatIfApi.preview(body)
    if (active()) { setResult(next); setRequest(body); setMessage('조건 비교를 계산했습니다. 설명과 공개 범위를 정해 실험으로 저장할 수 있습니다.') }
  })
  const save = () => run(async (active) => {
    if (!result || !request || !draft.title.trim()) return
    const saved = await whatIfApi.save(request, result, { ...draft, title: draft.title.trim() }, query)
    if (active()) { setTick((n) => n + 1); setOffset(0); setMessage(`실험 저장됨: ${saved.title} · ${saved.visibility === 'private' ? '개인' : '공유'}`) }
  })
  const reopen = (id: string) => run(async (active) => {
    const saved = await whatIfApi.experiment(id)
    if (!active() || !saved.preview_request) return
    setQuery(saved.query ?? ''); setPlan(null); setChanges(saved.preview_request.changes); setResult(null); setRequest(null)
    setModelSettings({ config: saved.preview_request.config, options: saved.preview_request.options })
    setDraft({ title: saved.title, purpose: saved.purpose ?? '', description: saved.description ?? '', assumptions: saved.assumptions ?? '', conclusion: saved.conclusion ?? '', visibility: saved.visibility })
    setStale(false); setBasisTick((n) => n + 1)
    setMessage('저장된 변경 조건을 불러왔습니다. 현재 기준에서 조건을 확인하고 “조건 비교 계산”을 눌러 재실행하세요.')
  })
  const add = (target: WhatIfChange['target']) => {
    const targets = targetsQ.data
    if (!targets || changes.length >= 8) return
    const anchor = target === 'output_size' ? targets.output_targets[0] : targets.anchors.find((row) => row.supported)?.id
    const node = targets.nodes.find((row) => target === 'node_clock_mhz' ? row.clock_supported : row.size_supported)?.id
    updateChanges([...changes, target === 'fps' ? { target, value: 30 } : target === 'node_clock_mhz' ? { target, node_id: node, value: 400 } : target === 'node_size' ? { target, node_id: node, width: 1920, height: 1080 } : { target, anchor_id: anchor, width: 1920, height: 1080 }])
  }
  return <div className="page tb-page">
    <p className="faint">{scope.project_ref} / {scope.scenario_id} / {scope.variant_id} · {modelSettings.config ? '불러온 실험의 모델 설정' : '기본 전력 모델'}과 과제 처리량 정책으로 비교합니다.</p>
    <div className="tb-grid">
      <Card id="wi-query" title="자연어 What-if" note="질문 해석 → 변경 대상 확인 → 계산 → 실험 저장" defaultWide>
        <div className="toolbar" style={{ flexWrap: 'wrap' }}>{EXAMPLES.map((example) => <button key={example} className="btn tb-mini" disabled={busy} onClick={() => { invalidate(); setQuery(example); setPlan(null); setChanges([]) }}>{example}</button>)}</div>
        <label className="collab-form">변경 조건 질문<textarea className="input" aria-label="변경 조건 질문" rows={3} maxLength={2000} value={query} onChange={(e) => { invalidate(); setQuery(e.target.value); setPlan(null); setChanges([]) }} placeholder="출력 크기 · FPS · IP clock 변경을 질문하세요." /></label>
        <button className="btn primary" disabled={busy || !query.trim() || targetsQ.loading || !!targetsQ.error} onClick={interpret}>변경 조건 해석</button>
        <p className="faint">해상도 · FPS · IP clock의 한국어/영어 질문을 지원합니다. 센서 모드, 압축, 화질, 복잡한 임의 조건은 지원 범위에서 제외됩니다.</p>
        {plan && <div className="collab-plan"><span className={`badge ${plan.status === 'ready' ? 'v-ok' : 'v-warn'}`}>{plan.status === 'ready' ? '해석 완료 · 조건 확인 필요' : plan.status === 'clarification' ? '대상을 명시하세요' : '지원 범위를 벗어난 질문'}</span>
          {plan.clarifications.map((item) => <p key={item.field}>{item.message}<br /><span className="faint">선택 가능한 대상: {item.choices.map((choice) => `${choice.label} (${choice.value})`).join(' · ')}</span></p>)}
          {plan.warnings.map((warning) => <p className="faint" key={warning}>{warning}</p>)}
        </div>}
      </Card>
      <Card id="wi-condition" title="계산할 변경 조건 확인" note="입력·중간·출력 크기를 구분하고 명시한 항목만 변경합니다." defaultWide>
        {targetsQ.error && <div className="err">{targetsQ.error}</div>}
        {targetsQ.data && <>
          <div className="faint">크기 기준: {targetsQ.data.anchors.map((anchor) => `${anchor.id} ${anchor.size.join('×')}${anchor.kind === 'sensor' ? ' (센서 유지)' : ''}`).join(' · ')}</div>
          <p className="faint">IP clock은 수동 하한이며 요구량·DVFS·공유 domain 제약에 따라 더 높게 적용될 수 있습니다. FPS는 가상 처리 주기의 변경이며 센서 지원 모드나 화질을 검증하지 않습니다.</p>
          <div className="toolbar" style={{ marginTop: 8, flexWrap: 'wrap' }}>{(Object.keys(CHANGE_LABELS) as WhatIfChange['target'][]).map((target) => <button className="btn tb-mini" key={target} disabled={busy || changes.length >= 8} onClick={() => add(target)}>+ {CHANGE_LABELS[target]}</button>)}</div>
          {changes.length ? changes.map((change, index) => <ChangeEditor key={index} change={change} targets={targetsQ.data!} disabled={busy} onChange={(next) => updateChanges(changes.map((row, at) => at === index ? next : row))} onRemove={() => updateChanges(changes.filter((_, at) => at !== index))} />) : <p className="faint">질문을 해석하거나 변경 항목을 추가하세요. 모호한 질문은 대상과 값을 직접 지정하세요.</p>}
          <button className="btn primary" disabled={busy || stale || !baselineHash || !changes.length || !changes.every(validChange)} onClick={preview}>조건 비교 계산</button>{' '}
          <button className="btn" disabled={busy} onClick={() => { invalidate(); setPlan(null); setStale(false); setBasisTick((n) => n + 1) }}>기준 갱신</button>
          <details><summary className="faint">모델 지원 범위</summary><ul>{targetsQ.data.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>
        </>}
      </Card>
      {result && <ResultView result={result} />}
      {result && <Card id="wi-save" title="실험 기록 저장" note="작성자와 계산 근거를 함께 기록합니다." defaultWide>
        <div className="collab-form">{([{ key: 'title', label: '실험 제목', max: 200 }, { key: 'purpose', label: '검토 목적', max: 4000 }, { key: 'description', label: '실험 상세 설명', max: 12000 }, { key: 'assumptions', label: '실험 가정 · 제약', max: 6000 }, { key: 'conclusion', label: '실험 결론', max: 6000 }] as const).map(({ key, label, max }) => <label key={key}>{label}<textarea className="input" aria-label={label} rows={key === 'description' ? 3 : 1} maxLength={max} value={draft[key]} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} /></label>)}
          <label>공개 범위<select aria-label="실험 공개 범위" value={draft.visibility} onChange={(e) => setDraft({ ...draft, visibility: e.target.value as 'private' | 'shared' })}><option value="private">개인 · 인증 사용자 본인</option><option value="shared">공유 · 인증된 사용자 열람</option></select></label>
          <p className="faint">개인 구분은 서버 사용자 인증이 활성화된 환경에서 적용됩니다.</p>
          <div><button className="btn primary" disabled={busy || !draft.title.trim()} onClick={save}>실험 저장</button></div>
        </div>
      </Card>}
      <Card id="wi-list" title="내 실험 · 공유 실험" note="저장된 조건을 불러와 현재 입력으로 다시 비교할 수 있습니다." defaultWide>
        <p className="faint">개인 구분은 서버 사용자 인증이 활성화된 환경에서 적용됩니다. 공유 실험은 인증된 사용자가 열람할 수 있습니다.</p>
        {savedQ.error && <div className="err">{savedQ.error} · 작성자 확인이 필요하면 설정에서 API 키를 연결하세요.</div>}
        {savedQ.loading ? <div className="faint">실험 불러오는 중…</div> : savedQ.data && <>
          <table className="tb-mini-table" style={{ width: '100%' }}><thead><tr><th>실험</th><th>공개</th><th>작성자 · 저장 시각</th><th /></tr></thead><tbody>{savedQ.data.items.map((experiment) => <tr key={experiment.id}><td>{experiment.title}<div className="faint">{experiment.purpose}</div></td><td>{experiment.visibility === 'private' ? '개인' : '공유'}</td><td>{experiment.created_by} · {date(experiment.created_at)}</td><td><button className="btn tb-mini" disabled={busy} onClick={() => reopen(experiment.id)}>조건 불러오기 · 재실행</button></td></tr>)}</tbody></table>
          {!savedQ.data.items.length && <p className="faint">아직 저장된 실험이 없습니다.</p>}
          <div className="toolbar"><button className="btn tb-mini" disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>이전 실험</button><span className="faint">총 {savedQ.data.total}건</span><button className="btn tb-mini" disabled={busy || !savedQ.data.has_next} onClick={() => setOffset(offset + 20)}>다음 실험</button></div>
        </>}
      </Card>
    </div>
    {busy && <p role="status">요청 처리 중…</p>}{message && <p role="status" className={stale ? 'err' : ''}>{message}</p>}
  </div>
}
function ChangeEditor({ change, targets, disabled, onChange, onRemove }: { change: WhatIfChange; targets: WhatIfTargets; disabled: boolean; onChange: (next: WhatIfChange) => void; onRemove: () => void }) {
  const size = ['anchor_size', 'node_size', 'output_size'].includes(change.target)
  const node = change.target === 'node_size' || change.target === 'node_clock_mhz'
  const choices = node ? targets.nodes.filter((row) => change.target === 'node_size' ? row.size_supported : row.clock_supported) : targets.anchors.filter((row) => row.supported && (change.target !== 'output_size' || row.kind === 'output'))
  return <fieldset className="wi-change" disabled={disabled}><legend>{CHANGE_LABELS[change.target]}</legend>
    {change.target !== 'fps' && <label>변경 대상<select aria-label={`${CHANGE_LABELS[change.target]} 대상`} value={(node ? change.node_id : change.anchor_id) ?? ''} onChange={(e) => onChange({ ...change, ...(node ? { node_id: e.target.value } : { anchor_id: e.target.value }) })}><option value="">대상 선택</option>{choices.map((row) => <option key={row.id} value={row.id}>{row.id} · {row.size.join('×')}</option>)}</select></label>}
    {size ? <><label>너비<input className="input" aria-label="변경 너비" type="number" min={16} max={16384} step={1} value={change.width ?? ''} onChange={(e) => onChange({ ...change, width: Number(e.target.value) })} /></label><label>높이<input className="input" aria-label="변경 높이" type="number" min={16} max={16384} step={1} value={change.height ?? ''} onChange={(e) => onChange({ ...change, height: Number(e.target.value) })} /></label></> : <label>{change.target === 'fps' ? 'FPS' : 'MHz'}<input className="input" aria-label={change.target === 'fps' ? '변경 FPS' : '변경 clock MHz'} type="number" min={1} max={change.target === 'fps' ? 240 : 5000} value={change.value ?? ''} onChange={(e) => onChange({ ...change, value: Number(e.target.value) })} /></label>}
    <button className="btn tb-mini" onClick={onRemove}>항목 제거</button>
  </fieldset>
}
function ResultView({ result }: { result: WhatIfResult }) {
  const before = result.baseline, after = result.candidate
  const metrics = [{ key: 'modeled_power_mw', label: '모델 합계', unit: 'mW' }, { key: 'cpu_power_mw', label: 'CPU', unit: 'mW' }, { key: 'ip_power_mw', label: 'IP', unit: 'mW' }, { key: 'memory_power_mw', label: '메모리 BW', unit: 'mW' }, { key: 'bw_mbs', label: 'BW', unit: 'MB/s' }, { key: 'fps', label: 'FPS', unit: 'fps' }, { key: 'period_ms', label: 'Frame period', unit: 'ms' }] as const
  const baseIps = new Map(before.report.ips.map((ip) => [ip.node, ip]))
  const explanations = new Map(result.delta.ips.map((ip) => [ip.node, ip.explanation]))
  const baseStages = new Map(before.report.stages.map((stage) => [stage.id, stage]))
  const delta = (a: number, b: number) => `${b - a >= 0 ? '+' : ''}${fmt(b - a, 2)}`
  return <>
    <Card id="wi-result" title="기준 대비 조건 변경 결과" note="요구 clock과 적용 clock을 구분하고 모델 범위를 함께 확인하세요." defaultWide>
      <table className="tb-mini-table" style={{ width: '100%' }}><thead><tr><th>항목</th><th>기준</th><th>변경</th><th>변화</th></tr></thead><tbody>{metrics.map(({ key, label, unit }) => <tr key={key}><th>{label} ({unit})</th><td className="mono">{fmt(before.metrics[key], 2)}</td><td className="mono">{fmt(after.metrics[key], 2)}</td><td className="mono">{delta(before.metrics[key], after.metrics[key])}</td></tr>)}<tr><th>처리량 조건</th><td>{before.metrics.feasible ? '충족' : '미달'}</td><td>{after.metrics.feasible ? '충족' : '미달'}</td><td>{after.report.verdict.reasons.join(' · ')}</td></tr></tbody></table>
      <div className="table-x"><table className="tb-mini-table" style={{ width: '100%' }}><thead><tr><th>IP</th><th>요구 clock MHz (기준 → 변경)</th><th>적용 clock MHz (기준 → 변경)</th><th>IP power mW (기준 → 변경)</th><th>변경 근거</th></tr></thead><tbody>{after.report.ips.map((ip) => { const base = baseIps.get(ip.node); return <tr key={ip.node}><th>{ip.node}</th><td>{fmt(base?.required_clock_mhz, 1)} → {fmt(ip.required_clock_mhz, 1)}</td><td>{fmt(base?.set_clock_mhz, 1)} → {fmt(ip.set_clock_mhz, 1)}</td><td>{fmt(base?.power_mw, 1)} → {fmt(ip.power_mw, 1)}</td><td title={explanations.get(ip.node)}>{clockExplanation(ip, explanations.get(ip.node))}</td></tr> })}</tbody></table></div>
      <table className="tb-mini-table" style={{ width: '100%' }}><thead><tr><th>Stage</th><th>HW ms (기준 → 변경)</th><th>예산 ms (기준 → 변경)</th><th>SW ms (기준 → 변경)</th></tr></thead><tbody>{after.report.stages.map((stage) => { const base = baseStages.get(stage.id); return <tr key={stage.id}><th>{stage.name}</th><td>{fmt(base?.hw_ms, 2)} → {fmt(stage.hw_ms, 2)}</td><td>{fmt(base?.budget_ms, 2)} → {fmt(stage.budget_ms, 2)}</td><td>{fmt(base?.sw_ms, 2)} → {fmt(stage.sw_ms, 2)}</td></tr> })}</tbody></table>
      {result.warnings.map((warning) => <p className="faint" key={warning}>{warning}</p>)}
    </Card>
    <Card id="wi-basis" title="전력 모델 범위 · 계산 근거" defaultWide>
      <p>표시한 합계: {after.coverage.scope} · {after.coverage.complete ? '모델 범위 충족' : '부분 모델'}</p>
      <p>전체 시스템 전력: {after.metrics.total_power_mw === null ? '제외·미모델 항목으로 계산되지 않음' : `${fmt(after.metrics.total_power_mw, 2)} mW`}</p>
      <p>미모델: {after.coverage.missing_components.join(' · ') || '없음'} / 제외: {after.coverage.excluded_components.join(' · ') || '없음'}</p>
      <ul>{after.coverage.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
      <details><summary>계산 모델 상세 · 버전 · 입력 식별값</summary><dl className="wi-lineage">{Object.entries(result.model_lineage).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—')}</dd></div>)}</dl></details>
    </Card>
  </>
}
