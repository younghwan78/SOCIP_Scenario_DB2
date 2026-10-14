import { useEffect, useMemo, useRef, useState } from 'react'
import type { Ctx } from '../App'
import { api, ApiError } from '../lib/api'
import { projectText } from '../lib/projects'
import { useCredentialKeyId } from '../lib/auth'
import { useAsync } from '../lib/route'
import { fmt } from '../lib/timingBudget'
import { answerLines, clockExplanation, describeChange, kindsOf, upsertChange, validChange, whatIfApi, type ChangeKindMeta, type ExperimentDraft, type FocusMetric, type PreviewRequest, type WhatIfChange, type WhatIfClarification, type WhatIfPlan, type WhatIfResult, type WhatIfScope, type WhatIfTargets } from '../lib/scenarioWhatIf'
import { Card } from '../components/TimingCharts'

const STATUS: Record<WhatIfPlan['status'], { label: string; cls: string }> = {
  ready: { label: '해석 완료 · 조건 확인 후 계산', cls: 'v-ok' }, partial: { label: '일부만 해석 · 나머지는 아래 참고', cls: 'v-warn' },
  clarification: { label: '선택이 필요합니다', cls: 'v-warn' }, unsupported: { label: '계산할 조건을 찾지 못함', cls: 'v-warn' },
  no_change: { label: '기준과 같아 바꿀 조건 없음', cls: 'v-warn' },
}
/** Questions built from the selected variant's own baseline, so every example is answerable as written. */
function examplesFor(targets: WhatIfTargets | undefined): string[] {
  if (!targets) return []
  const out: string[] = []
  const record = targets.anchors.find((a) => a.kind === 'output' && (a.role === 'record' || (!a.role && /record|video|enc/i.test(a.id))))
  if (record) out.push(record.size[0] * record.size[1] > 1920 * 1080 ? '녹화를 FHD로 낮추면 전력은 얼마나 줄어?' : '녹화를 UHD로 올리면 BW와 전력은?')
  if (targets.fps) out.push(targets.fps >= 60 ? 'FPS 절반이면 clock과 전력은?' : `FPS를 ${targets.fps * 2}으로 올리면 timing 버틸 수 있어?`)
  const stream = targets.streams?.find((st) => st.primary)
  if (!record && stream) out.push(stream.size[0] * stream.size[1] > 1920 * 1080 ? 'FHD로 낮추면 전력과 BW는?' : 'UHD로 올리면 전력과 BW는?')
  const ip = targets.nodes.find((n) => n.clock_supported && n.category === 'codec') ?? targets.nodes.find((n) => n.clock_supported)
  if (ip) out.push(`${ip.ip ?? ip.id} clock 20% 낮추면 timing 여유는?`)
  if (record && targets.fps) out.push('미리보기는 그대로 두고 녹화 HD, FPS 30이면?')
  return out
}
const emptyDraft: ExperimentDraft = { title: '', purpose: '', description: '', assumptions: '', conclusion: '', visibility: 'private' }
const date = (value: string) => new Date(value).toLocaleString('ko-KR')
const textError = (error: unknown) => error instanceof ApiError && error.status === 409 ? '기준 입력이 변경되었습니다. 조건 해석 또는 기준 갱신 후 다시 계산하세요.' : error instanceof Error ? error.message : String(error)

export function ScenarioWhatIfPage({ ctx }: { ctx: Ctx }) {
  const credential = useCredentialKeyId()
  const ready = !!(ctx.project && ctx.scenario && ctx.variant)
  return <div className="page tb-page">
    <ScopePicker ctx={ctx} />
    {ready ? <WhatIfBody key={`${ctx.project}|${ctx.scenario}|${ctx.variant}|${credential}`} scope={{ project_ref: ctx.project, scenario_id: ctx.scenario, variant_id: ctx.variant }} />
      : <p className="faint">과제 · scenario · variant를 먼저 선택하세요. 질문은 선택한 variant를 기준으로 해석하고 계산합니다.</p>}
  </div>
}
/** ① 과제 → scenario → variant: the question is always asked against an explicit baseline. */
function ScopePicker({ ctx }: { ctx: Ctx }) {
  const projects = ctx.projects ?? [], catalog = ctx.catalog ?? []
  const variantsQ = useAsync(() => (ctx.scenario ? api.variants(ctx.scenario).catch(() => ({ items: [], total: 0 })) : Promise.resolve({ items: [], total: 0 })), [ctx.scenario])
  const variants = variantsQ.data?.items ?? []
  const go = (params: Record<string, string | undefined>) => ctx.navigate?.('whatif', params)
  const dc = (v: { design_conditions?: Record<string, unknown> | null }) => {
    const d = v.design_conditions ?? {}
    return [d.resolution ?? d.record_resolution, d.fps ? `${d.fps}fps` : null].filter(Boolean).join(' · ')
  }
  return <section className="wi-scope" aria-label="What-if 대상 선택">
    <span className="wi-step">① 대상</span>
    <label>과제<select aria-label="What-if 과제" value={ctx.project} onChange={(e) => ctx.setProject?.(e.target.value)}>
      {!projects.some((p) => p.id === ctx.project) && <option value={ctx.project}>{ctx.project || '과제 선택'}</option>}
      {projects.map((p) => <option key={p.id} value={p.id}>{projectText(p)}</option>)}</select></label>
    <label>Scenario<select aria-label="What-if scenario" value={ctx.scenario} onChange={(e) => go({ scenario: e.target.value, variant: undefined })}>
      {!catalog.some((c) => c.scenario_id === ctx.scenario) && <option value={ctx.scenario}>{ctx.scenario || 'scenario 선택'}</option>}
      {catalog.map((c) => <option key={c.scenario_id} value={c.scenario_id}>{c.scenario_name} ({c.variant_count})</option>)}</select></label>
    <label>Variant (기준)<select aria-label="What-if variant" value={ctx.variant} onChange={(e) => go({ scenario: ctx.scenario, variant: e.target.value || undefined })}>
      <option value="">variant 선택</option>
      {!variants.some((v) => v.id === ctx.variant) && ctx.variant && <option value={ctx.variant}>{ctx.variant}</option>}
      {variants.map((v) => <option key={v.id} value={v.id}>{v.id}{dc(v) ? ` — ${dc(v)}` : ''}</option>)}</select></label>
  </section>
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
  const [pending, setPending] = useState<WhatIfClarification[]>([])
  const [focus, setFocus] = useState<FocusMetric[]>([])
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
    const next = await whatIfApi.plan(scope, query.trim(), modelSettings)
    if (active()) { setPlan(next); setPending(next.clarifications); setFocus(next.focus ?? []); setChanges(next.changes); setResult(null); setRequest(null); setStale(false) }
  })
  const choose = (index: number, change: WhatIfChange) => { updateChanges(upsertChange(changes, change)); setPending((rows) => rows.filter((_, at) => at !== index)) }
  const examples = useMemo(() => examplesFor(targetsQ.data), [targetsQ.data])
  const kinds = useMemo(() => kindsOf(targetsQ.data), [targetsQ.data])
  const valid = (change: WhatIfChange) => validChange(change, kinds)
  const canPreview = !busy && !stale && !!(plan?.baseline_hash ?? targetsQ.data?.baseline_hash) && changes.length > 0 && changes.every(valid)
  const baselineHash = plan?.baseline_hash ?? targetsQ.data?.baseline_hash
  const preview = () => run(async (active) => {
    if (!baselineHash || stale || !changes.length || !changes.every((change) => validChange(change, kindsOf(targetsQ.data)))) return
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
    setQuery(saved.query ?? ''); setPlan(null); setPending([]); setFocus([]); setChanges(saved.preview_request.changes); setResult(null); setRequest(null)
    setModelSettings({ config: saved.preview_request.config, options: saved.preview_request.options })
    setDraft({ title: saved.title, purpose: saved.purpose ?? '', description: saved.description ?? '', assumptions: saved.assumptions ?? '', conclusion: saved.conclusion ?? '', visibility: saved.visibility })
    setStale(false); setBasisTick((n) => n + 1)
    setMessage('저장된 변경 조건을 불러왔습니다. 현재 기준에서 조건을 확인하고 “조건 비교 계산”을 눌러 재실행하세요.')
  })
  /** New editable row from the kind's first available instance (size/value prefilled with the baseline). */
  const add = (kind: ChangeKindMeta) => {
    if (changes.length >= 8) return
    const first = kind.choices[0]
    const row: WhatIfChange = { target: kind.target }
    if (kind.selector && first && kind.selector !== null) row[kind.selector] = first.id
    if (kind.needs_param && first?.param) row.param = first.param
    if (kind.shape === 'size') { row.width = first?.size?.[0] ?? 1920; row.height = first?.size?.[1] ?? 1080 }
    else row.value = first?.value ?? (kind.target === 'node_clock_mhz' ? 400 : targetsQ.data?.fps ?? 30)
    updateChanges([...changes, row])
  }
  const t = targetsQ.data
  const resetQuestion = (value: string) => { invalidate(); setQuery(value); setPlan(null); setPending([]); setChanges([]) }
  return <>
    <p className="faint">기준 {scope.variant_id}{t ? ` · FPS ${t.fps ?? '?'} · ${t.anchors.filter((a) => a.kind !== 'intermediate').map((a) => `${a.id} ${a.size.join('×')}`).join(' · ')}` : ''} · {modelSettings.config ? '불러온 실험의 모델 설정' : '기본 전력 모델'}과 과제 처리량 정책으로 비교합니다.</p>
    <div className="tb-grid">
      <Card id="wi-query" title="② 질문" note="자유롭게 질문하세요 — 해석한 조건을 확인한 뒤 계산합니다" defaultWide>
        <label className="collab-form">변경 조건 질문<textarea className="input" aria-label="변경 조건 질문" rows={3} maxLength={2000} value={query} onChange={(e) => resetQuestion(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && query.trim()) interpret() }}
          placeholder="예: 녹화를 FHD 60으로 바꾸면 BW랑 전력은? · MFC clock 20% 낮추면 timing 여유는? · FPS 절반이면?" /></label>
        {examples.length > 0 && <div className="toolbar" style={{ flexWrap: 'wrap' }}><span className="faint">예시</span>{examples.map((example) => <button key={example} className="btn tb-mini" disabled={busy} onClick={() => resetQuestion(example)}>{example}</button>)}</div>}
        <button className="btn primary" disabled={busy || !query.trim() || targetsQ.loading || !!targetsQ.error} onClick={interpret}>변경 조건 해석</button>
        <span className="faint"> Ctrl+Enter</span>
        <details><summary className="faint">해석할 수 있는 것</summary><ul className="faint">
          <li>출력 크기: FHD·UHD·QHD·HD·4K·8K·1080p·1920x1080, “절반”, “30% 줄이면” — 녹화/미리보기/anchor 이름으로 대상 지정 (지정이 없으면 녹화 출력)</li>
          <li>FPS: “60fps”, “FPS 60”, “UHD60”, “4K@30”, “절반”, “2배”</li>
          <li>IP clock 하한: “mfc 600 MHz”, “인코더 0.6 GHz”, “GDC clock 20% 낮추면” (상대값은 기준 적용 clock 대비)</li>
          <li>관심 지표: 전력 · clock · BW · timing/여유 · 가능 여부 → 답변에서 먼저 보여줍니다</li>
          <li>코덱·압축·EIS/HDR·전압·CPU 배치·센서 mode는 해석하지 않고 어느 화면에서 다루는지 알려줍니다</li></ul></details>
        {plan && <div className="collab-plan wi-plan">
          <span className={`badge ${STATUS[plan.status].cls}`}>{STATUS[plan.status].label}</span>
          {changes.length > 0 && <ul className="wi-interp">{changes.map((change, index) => {
            const at = plan.changes.findIndex((row) => describeChange(row) === describeChange(change))
            return <li key={index}><b>{describeChange(change)}</b>{at >= 0 && plan.sources?.[at] && <span className="faint"> ← “{plan.sources[at]}”</span>}</li>
          })}</ul>}
          {plan.kept?.length ? <p className="faint">유지: {plan.kept.join(' · ')}</p> : null}
          {plan.notes?.map((note) => <p className="faint" key={note}>{note}</p>)}
          {pending.map((item, index) => <div className="wi-clarify" key={`${item.field}-${index}`}>
            <p>{item.message}{item.source && <span className="faint"> — “{item.source}”</span>}</p>
            <div className="toolbar" style={{ flexWrap: 'wrap' }}>{item.choices.filter((choice) => choice.change).map((choice) => <button key={choice.label} className="btn tb-mini" disabled={busy} onClick={() => choose(index, choice.change!)}>{choice.label}</button>)}</div>
          </div>)}
          {plan.ignored?.length ? <div className="wi-ignored"><b>해석하지 않은 부분</b><ul>{plan.ignored.map((item) => <li key={item.text + item.reason}>“{item.text}” — {item.reason}{item.hint && <span className="faint"> → {item.hint}</span>}</li>)}</ul></div> : null}
          {(plan.status === 'unsupported' || plan.status === 'no_change') && plan.warnings.map((warning) => <p className="faint" key={warning}>{warning}</p>)}
          {changes.length > 0 && <div className="toolbar"><button className="btn primary" disabled={!canPreview || pending.length > 0} onClick={preview}>이 조건으로 계산</button>
            {pending.length > 0 && <span className="faint">선택이 남아 있습니다 — 선택하거나 아래에서 직접 조정하세요.</span>}</div>}
        </div>}
      </Card>
      <Card id="wi-condition" title="③ 계산할 조건 (직접 조정)" note="해석 결과를 고치거나 질문 없이 직접 추가할 수 있습니다. 명시한 항목만 변경합니다." defaultWide>
        {targetsQ.error && <div className="err">{targetsQ.error}</div>}
        {targetsQ.data && <>
          {targetsQ.data.anchors.length > 0 && <div className="faint">크기 기준: {targetsQ.data.anchors.map((anchor) => `${anchor.id} ${anchor.size.join('×')}${anchor.kind === 'sensor' ? ' (센서 유지)' : anchor.role ? ` (${anchor.role === 'record' ? '녹화' : '미리보기'})` : ''}`).join(' · ')}</div>}
          {!!targetsQ.data.streams?.length && <div className="faint">스트림: {targetsQ.data.streams.map((st) => `${st.id}${st.primary ? ' (주)' : ''}`).join(' · ')}</div>}
          {targetsQ.data.capability && <p className="faint">{targetsQ.data.capability.soc_ref ?? 'SoC 미정'} · DVFS group 정책 {targetsQ.data.capability.soc_profile === 'generic' ? '기본값' : targetsQ.data.capability.soc_profile}{targetsQ.data.capability.notes.map((note) => ` · ${note}`).join('')}</p>}
          <p className="faint">IP clock은 수동 하한이며 요구량·DVFS·공유 domain 제약에 따라 더 높게 적용될 수 있습니다. FPS는 가상 처리 주기의 변경이며 센서 지원 모드나 화질을 검증하지 않습니다.</p>
          {kinds.length === 0 ? <p className="err">이 variant에는 What-if로 바꿀 수 있는 조건이 없습니다 (크기 기준·스트림·clock 모델이 있는 IP·FPS 모두 없음).</p>
            : <div className="toolbar" style={{ marginTop: 8, flexWrap: 'wrap' }}>{kinds.map((kind) => <button className="btn tb-mini" key={kind.target} title={kind.description} disabled={busy || changes.length >= 8} onClick={() => add(kind)}>+ {kind.label}</button>)}</div>}
          {changes.length ? changes.map((change, index) => <ChangeEditor key={index} change={change} kinds={kinds} disabled={busy} onChange={(next) => updateChanges(changes.map((row, at) => at === index ? next : row))} onRemove={() => updateChanges(changes.filter((_, at) => at !== index))} />) : <p className="faint">질문을 해석하거나 변경 항목을 추가하세요. 모호한 질문은 대상과 값을 직접 지정하세요.</p>}
          <button className="btn primary" disabled={busy || stale || !baselineHash || !changes.length || !changes.every(valid)} onClick={preview}>조건 비교 계산</button>{' '}
          <button className="btn" disabled={busy} onClick={() => { invalidate(); setPlan(null); setStale(false); setBasisTick((n) => n + 1) }}>기준 갱신</button>
          <details><summary className="faint">모델 지원 범위</summary><ul>{targetsQ.data.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>
        </>}
      </Card>
      {result && <ResultView result={result} focus={focus} query={plan ? query : ''} />}
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
  </>
}
/** Generic editor driven by the change kind's metadata (shape · selector · param · unit · max). */
function ChangeEditor({ change, kinds, disabled, onChange, onRemove }: { change: WhatIfChange; kinds: ChangeKindMeta[]; disabled: boolean; onChange: (next: WhatIfChange) => void; onRemove: () => void }) {
  const kind = kinds.find((k) => k.target === change.target)
  const label = kind?.label ?? change.target
  const selector = kind?.selector ?? null
  const choiceText = (row: ChangeKindMeta['choices'][number]) => [row.id, row.size ? row.size.join('×') : null, row.label, row.role === 'record' ? '녹화' : row.role === 'preview' ? '미리보기' : null, row.ip && row.ip !== row.id ? row.ip : null].filter(Boolean).join(' · ')
  const valueLabel = change.target === 'fps' ? 'FPS' : change.target === 'node_clock_mhz' ? 'MHz' : kind?.unit || '값'
  const valueAria = change.target === 'fps' ? '변경 FPS' : change.target === 'node_clock_mhz' ? '변경 clock MHz' : `변경 ${label}`
  return <fieldset className="wi-change" disabled={disabled}><legend title={kind?.description}>{label}</legend>
    {selector && <label>변경 대상<select aria-label={`${label} 대상`} value={change[selector] ?? ''} onChange={(e) => {
      const choice = kind?.choices.find((row) => row.id === e.target.value)
      onChange({ ...change, [selector]: e.target.value || undefined, ...(kind?.needs_param && choice?.param ? { param: choice.param } : {}) })
    }}><option value="">{kind?.selector_optional ? '자동 (단일 대상)' : '대상 선택'}</option>{(kind?.choices ?? []).map((row) => <option key={`${row.id}-${row.param ?? ''}`} value={row.id}>{choiceText(row)}</option>)}</select></label>}
    {kind?.shape === 'size' || (!kind && change.width != null)
      ? <><label>너비<input className="input" aria-label="변경 너비" type="number" min={16} max={16384} step={1} value={change.width ?? ''} onChange={(e) => onChange({ ...change, width: Number(e.target.value) })} /></label><label>높이<input className="input" aria-label="변경 높이" type="number" min={16} max={16384} step={1} value={change.height ?? ''} onChange={(e) => onChange({ ...change, height: Number(e.target.value) })} /></label></>
      : <label>{valueLabel}<input className="input" aria-label={valueAria} type="number" min={1} max={kind?.max_value ?? undefined} value={change.value ?? ''} onChange={(e) => onChange({ ...change, value: Number(e.target.value) })} /></label>}
    <button className="btn tb-mini" onClick={onRemove}>항목 제거</button>
  </fieldset>
}
const FOCUS_ROWS: Record<FocusMetric, string[]> = { power: ['modeled_power_mw', 'cpu_power_mw', 'ip_power_mw', 'memory_power_mw'], bw: ['bw_mbs', 'memory_power_mw'], timing: ['period_ms', 'fps'], clock: [], feasible: [] }
function ResultView({ result, focus, query }: { result: WhatIfResult; focus: FocusMetric[]; query: string }) {
  const before = result.baseline, after = result.candidate
  const hot = new Set(focus.flatMap((key) => FOCUS_ROWS[key]))
  const lines = answerLines(result, focus)
  const metrics = [{ key: 'modeled_power_mw', label: '모델 합계', unit: 'mW' }, { key: 'cpu_power_mw', label: 'CPU', unit: 'mW' }, { key: 'ip_power_mw', label: 'IP', unit: 'mW' }, { key: 'memory_power_mw', label: '메모리 BW', unit: 'mW' }, { key: 'bw_mbs', label: 'BW', unit: 'MB/s' }, { key: 'fps', label: 'FPS', unit: 'fps' }, { key: 'period_ms', label: 'Frame period', unit: 'ms' }] as const
  const baseIps = new Map(before.report.ips.map((ip) => [ip.node, ip]))
  const explanations = new Map(result.delta.ips.map((ip) => [ip.node, ip.explanation]))
  const baseStages = new Map(before.report.stages.map((stage) => [stage.id, stage]))
  const delta = (a: number, b: number) => `${b - a >= 0 ? '+' : ''}${fmt(b - a, 2)}`
  return <>
    <Card id="wi-answer" title="답변" note={query ? `“${query}”` : '저장된 조건 재실행'} defaultWide>
      <ul className="wi-answer">{lines.map((line) => <li key={line.key} className={line.warn ? 'warn' : ''}>{line.text}</li>)}</ul>
      <p className="faint">{result.normalized_condition.changes.map(describeChange).join(' · ')} · 모델 범위: {after.coverage.scope}{after.coverage.complete ? '' : ' (부분 모델 — 전체 기기 전력 아님)'}</p>
    </Card>
    <Card id="wi-result" title="기준 대비 조건 변경 결과" note="요구 clock과 적용 clock을 구분하고 모델 범위를 함께 확인하세요." defaultWide>
      <table className="tb-mini-table" style={{ width: '100%' }}><thead><tr><th>항목</th><th>기준</th><th>변경</th><th>변화</th></tr></thead><tbody>{metrics.map(({ key, label, unit }) => <tr key={key} className={hot.has(key) ? 'wi-focus' : ''}><th>{label} ({unit})</th><td className="mono">{fmt(before.metrics[key], 2)}</td><td className="mono">{fmt(after.metrics[key], 2)}</td><td className="mono">{delta(before.metrics[key], after.metrics[key])}</td></tr>)}<tr><th>처리량 조건</th><td>{before.metrics.feasible ? '충족' : '미달'}</td><td>{after.metrics.feasible ? '충족' : '미달'}</td><td>{after.report.verdict.reasons.join(' · ')}</td></tr></tbody></table>
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
