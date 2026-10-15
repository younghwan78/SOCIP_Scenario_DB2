import { useEffect, useMemo, useRef, useState } from 'react'
import type { Ctx } from '../App'
import { api, ApiError } from '../lib/api'
import { projectText } from '../lib/projects'
import { useCredentialKeyId } from '../lib/auth'
import { useAsync } from '../lib/route'
import { fmt } from '../lib/timingBudget'
import { clockExplanation, describeChange, kindsOf, upsertChange, validChange, whatIfApi, type AskKind, type AskRequest, type AskResponse, type ChangeKindMeta, type ExperimentDraft, type FocusMetric, type PreviewRequest, type WhatIfChange, type WhatIfResult, type WhatIfScope, type WhatIfTargets } from '../lib/scenarioWhatIf'
import { Card } from '../components/TimingCharts'

const ASK_FALLBACK: { ask: AskKind; label: string; description: string }[] = [
  { ask: 'what_if', label: '조건 바꿔보기', description: 'DVFS level · IP clock · 크기 · FPS를 바꾸면 timing · 전력 · BW가 어떻게 되나' },
  { ask: 'search_limit', label: '어디까지 낮출 수 있나', description: 'DVFS domain level을 한 단계씩 낮추며 timing을 충족하는 최저 level 탐색' },
  { ask: 'diagnose', label: '병목 찾기', description: '기준 조건에서 가장 빠듯한 구간 · IP와 domain별 여유' },
]
const VERDICT: Record<string, { label: string; cls: string }> = {
  ok: { label: '가능', cls: 'v-ok' }, fail: { label: '불가', cls: 'v-fail' }, info: { label: '결과', cls: 'v-na' }, boundary: { label: '더 바꿀 수 없음', cls: 'v-warn' },
}
const SIZE_PRESETS: [string, number, number][] = [['HD', 1280, 720], ['FHD', 1920, 1080], ['QHD', 2560, 1440], ['UHD', 3840, 2160], ['8K', 7680, 4320]]
const FPS_PRESETS = [15, 24, 30, 60, 120]
/** Example questions from the variant's own targets (shown only when the in-house LLM is connected). */
function examplesFor(t: WhatIfTargets | undefined): string[] {
  if (!t) return []
  const out: string[] = []
  const dom = t.domains?.find((d) => d.index > 0) ?? t.domains?.[0]
  if (dom) out.push(`${dom.id} level을 하나 낮추면 timing에 문제가 없어?`, `${dom.id} 어디까지 낮출 수 있어?`)
  out.push('어디가 timing 병목이야?')
  const record = t.anchors.find((a) => a.kind === 'output' && a.role === 'record')
  if (record) out.push(record.size[0] * record.size[1] > 1920 * 1080 ? '녹화를 FHD로 낮추면 전력은 얼마나 줄어?' : '녹화를 UHD로 올리면 BW와 전력은?')
  return out
}
const emptyDraft: ExperimentDraft = { title: '', purpose: '', description: '', assumptions: '', conclusion: '', visibility: 'private' }
const date = (value: string) => new Date(value).toLocaleString('ko-KR')
const textError = (error: unknown) => error instanceof ApiError && error.status === 409 ? '기준 입력이 변경되었습니다. 기준 갱신 후 다시 계산하세요.' : error instanceof Error ? error.message : String(error)

export function ScenarioWhatIfPage({ ctx }: { ctx: Ctx }) {
  const credential = useCredentialKeyId()
  const ready = !!(ctx.project && ctx.scenario && ctx.variant)
  return <div className="page tb-page">
    <ScopePicker ctx={ctx} />
    {ready ? <WhatIfBody key={`${ctx.project}|${ctx.scenario}|${ctx.variant}|${credential}`} scope={{ project_ref: ctx.project, scenario_id: ctx.scenario, variant_id: ctx.variant }} />
      : <p className="faint">과제 · scenario · variant를 먼저 선택하세요. 조건은 선택한 variant를 기준으로 계산합니다.</p>}
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
  const t = targetsQ.data
  const kinds = useMemo(() => kindsOf(t), [t])
  const domains = t?.domains ?? []
  const asks = t?.asks ?? ASK_FALLBACK
  const llm = t?.llm?.available ?? false
  const [askKind, setAskKind] = useState<AskKind>('what_if')
  const [changes, setChanges] = useState<WhatIfChange[]>([])
  const [searchDomains, setSearchDomains] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [asked, setAsked] = useState('')
  const [resp, setResp] = useState<AskResponse | null>(null)
  const [dirty, setDirty] = useState(false)
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
  const run = async (action: (active: () => boolean) => Promise<void>) => {
    if (busyRef.current) return
    const sequence = generation.current
    busyRef.current = true; setBusy(true); setMessage('')
    const active = () => live.current && generation.current === sequence
    try { await action(active) } catch (error) { if (active()) { setMessage(textError(error)); if (error instanceof ApiError && error.status === 409) { setStale(true); setResp(null); setRequest(null) } } }
    finally { busyRef.current = false; if (live.current) setBusy(false) }
  }
  /** Builder edits keep the last answer on screen but mark it as not matching the conditions any more. */
  const edited = () => { generation.current++; setDirty(true); setRequest(null) }
  const updateChanges = (next: WhatIfChange[]) => { edited(); setChanges(next) }
  const ask = (payload: Omit<AskRequest, keyof WhatIfScope>, label: string) => run(async (active) => {
    const res = await whatIfApi.ask({ ...scope, ...modelSettings, ...payload })
    if (!active()) return
    setResp(res); setAsked(label); setDirty(false); setStale(false)
    if (res.plan) {   // what was executed (or interpreted) becomes the builder state, editable from here
      setAskKind(res.plan.ask)
      if (res.plan.ask === 'what_if') setChanges(res.plan.changes)
      if (res.plan.ask === 'search_limit') setSearchDomains(res.plan.search_domains)
    }
    setRequest(res.result ? { ...scope, ...modelSettings, changes: res.result.normalized_condition.changes, expected_baseline_hash: res.baseline_hash } : null)
  })
  const builderReady = !stale && !!t && (askKind !== 'what_if' || (changes.length > 0 && changes.every((c) => validChange(c, kinds))))
  const answerBuilder = () => ask(askKind === 'what_if' ? { ask: 'what_if', changes } : askKind === 'search_limit' ? { ask: 'search_limit', search_domains: searchDomains } : { ask: 'diagnose' },
    askKind === 'what_if' ? changes.map(describeChange).join(' · ') : askKind === 'search_limit' ? `한계 탐색: ${searchDomains.join(', ') || '모든 domain'}` : '병목 찾기')
  const askQuestion = () => { if (query.trim()) ask({ query: query.trim() }, query.trim()) }
  const save = () => run(async (active) => {
    if (!resp?.result || !request || !draft.title.trim()) return
    const saved = await whatIfApi.save(request, resp.result, { ...draft, title: draft.title.trim() }, asked)
    if (active()) { setTick((n) => n + 1); setOffset(0); setMessage(`실험 저장됨: ${saved.title} · ${saved.visibility === 'private' ? '개인' : '공유'}`) }
  })
  const reopen = (id: string) => run(async (active) => {
    const saved = await whatIfApi.experiment(id)
    if (!active() || !saved.preview_request) return
    setAskKind('what_if'); setChanges(saved.preview_request.changes); setResp(null); setRequest(null); setQuery(saved.query ?? '')
    setModelSettings({ config: saved.preview_request.config, options: saved.preview_request.options })
    setDraft({ title: saved.title, purpose: saved.purpose ?? '', description: saved.description ?? '', assumptions: saved.assumptions ?? '', conclusion: saved.conclusion ?? '', visibility: saved.visibility })
    setStale(false); setBasisTick((n) => n + 1)
    setMessage('저장된 조건을 불러왔습니다. 현재 기준으로 “답 보기”를 눌러 다시 계산하세요.')
  })
  /** New row from the kind's first instance, prefilled with something worth asking (one DVFS level down). */
  const add = (kind: ChangeKindMeta) => {
    if (changes.length >= 8) return
    const first = kind.choices.find((c) => !changes.some((row) => row.target === kind.target && kind.selector && row[kind.selector] === c.id)) ?? kind.choices[0]
    const row: WhatIfChange = { target: kind.target }
    if (kind.selector && first) row[kind.selector] = first.id as never
    if (kind.needs_param && first?.param) row.param = first.param
    if (kind.shape === 'size') { row.width = first?.size?.[0] ?? 1920; row.height = first?.size?.[1] ?? 1080 }
    else if (kind.shape === 'level') {
      const ladder = first?.ladder ?? [], at = ladder.findIndex((lv) => lv.level === first?.level)
      row.level = ladder[Math.max(0, at - 1)]?.level ?? first?.level ?? 0
    } else row.value = first?.value ?? (kind.target === 'node_clock_mhz' ? (t?.nodes.find((n) => n.id === first?.id)?.clock_mhz ?? 400) : t?.fps ?? 30)
    updateChanges([...changes, row])
  }
  const interp = resp?.interpretation
  const examples = useMemo(() => (llm ? examplesFor(t) : []), [llm, t])
  return <>
    <p className="faint">기준 {scope.variant_id}{t ? ` · FPS ${t.fps ?? '?'}${domains.length ? ` · ${domains.map((d) => `${d.id} L${d.level} ${d.mhz}MHz${d.index === 0 ? '(최저)' : ''}`).join(' · ')}` : ''}` : ''} · {modelSettings.config ? '불러온 실험의 모델 설정' : '기본 전력 모델'}과 과제 처리량 정책으로 계산합니다.</p>
    <div className="tb-grid">
      <Card id="wi-build" title="② 무엇을 알고 싶나요" note="질문 종류와 조건을 고르면 Timing Budget 엔진으로 계산해 답합니다" defaultWide>
        {targetsQ.error && <div className="err">{targetsQ.error}</div>}
        {llm ? <div className="wi-nl">
          <label className="collab-form">자연어 질문 <span className="badge v-na">사내 LLM{t?.llm?.model ? ` · ${t.llm.model}` : ''}</span>
            <textarea className="input" aria-label="자연어 질문" rows={2} maxLength={2000} value={query} onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) askQuestion() }}
              placeholder="예: INTCAM level을 하나 낮추면 timing에 문제가 없어? — 해석 결과는 아래 조건으로 채워지고 바로 계산합니다" /></label>
          <div className="toolbar" style={{ flexWrap: 'wrap' }}>
            <button className="btn primary" disabled={busy || !query.trim() || !t} onClick={askQuestion}>질문하기</button><span className="faint">Ctrl+Enter</span>
            {examples.map((example) => <button key={example} className="btn tb-mini" disabled={busy} onClick={() => setQuery(example)}>{example}</button>)}
          </div>
        </div> : t && <p className="faint">자연어 질문은 사내 LLM 연결 시 사용할 수 있습니다 (SCENARIO_DB_WHATIF_LLM_BASE_URL · _MODEL). 아래에서 조건을 고르세요.</p>}
        {interp?.status === 'llm_unavailable' && <p className="err">자연어 해석 불가 — {interp.reason}. 아래에서 조건을 골라 계산하세요.</p>}
        <div className="seg wi-asks" role="group" aria-label="질문 종류">{asks.map((a) => <button key={a.ask} className={askKind === a.ask ? 'on' : ''} title={a.description} onClick={() => { edited(); setAskKind(a.ask) }}>{a.label}</button>)}</div>
        <p className="faint" style={{ margin: '4px 0 8px' }}>{asks.find((a) => a.ask === askKind)?.description}</p>
        {askKind === 'what_if' && t && <>
          {kinds.length === 0 ? <p className="err">이 variant에는 What-if로 바꿀 수 있는 조건이 없습니다.</p>
            : <div className="toolbar" style={{ flexWrap: 'wrap' }}>{kinds.map((kind) => <button className="btn tb-mini" key={kind.target} title={kind.description} disabled={busy || changes.length >= 8} onClick={() => add(kind)}>+ {kind.label}</button>)}</div>}
          {changes.map((change, index) => <ChangeEditor key={index} change={change} kinds={kinds} targets={t} disabled={busy}
            onChange={(next) => updateChanges(changes.map((row, at) => at === index ? next : row))} onRemove={() => updateChanges(changes.filter((_, at) => at !== index))} />)}
          {!changes.length && <p className="faint">바꿀 조건을 추가하세요. 예: + DVFS level → INTCAM → 한 단계 낮은 level.</p>}
        </>}
        {askKind === 'search_limit' && <div className="wi-domains" role="group" aria-label="탐색할 domain">
          {domains.length === 0 ? <p className="err">이 variant에는 level을 바꿀 수 있는 DVFS domain이 없습니다.</p> : domains.map((d) => {
            const on = searchDomains.includes(d.id)
            return <label key={d.id} className={`wi-chip ${on ? 'on' : ''}`}><input type="checkbox" checked={on} onChange={() => { edited(); setSearchDomains(on ? searchDomains.filter((x) => x !== d.id) : [...searchDomains, d.id]) }} />
              {d.id} · L{d.level} {d.mhz} MHz{d.index === 0 ? ' · 최저 OPP' : ` · ${d.index}단계 아래까지`}<span className="faint"> ({d.ips.join(', ')})</span></label>
          })}
          {domains.length > 0 && <span className="faint">선택하지 않으면 모든 domain을 탐색합니다.</span>}
        </div>}
        <div className="toolbar" style={{ marginTop: 8 }}>
          <button className="btn primary" disabled={busy || !builderReady} onClick={answerBuilder}>답 보기</button>
          <button className="btn" disabled={busy} onClick={() => { edited(); setResp(null); setStale(false); setBasisTick((n) => n + 1) }}>기준 갱신</button>
        </div>
        {t && <details><summary className="faint">모델 지원 범위</summary><ul>{t.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>}
      </Card>
      {resp && <AnswerView resp={resp} asked={asked} dirty={dirty} busy={busy}
        onAction={(a) => { setAskKind(a.ask); if (a.search_domains) setSearchDomains(a.search_domains); ask({ ask: a.ask, search_domains: a.search_domains }, a.label) }}
        onChoose={(change) => { const next = upsertChange(resp.plan?.changes ?? [], change); setAskKind('what_if'); setChanges(next); ask({ ask: 'what_if', changes: next }, next.map(describeChange).join(' · ')) }} />}
      {resp?.result && <ResultView result={resp.result} focus={resp.plan?.focus ?? []} />}
      {resp?.search && <SearchView rows={resp.search} />}
      {resp?.diagnose && <DiagnoseView diag={resp.diagnose} />}
      {resp?.result && request && <Card id="wi-save" title="실험 기록 저장" note="작성자와 계산 근거를 함께 기록합니다." defaultWide>
        <div className="collab-form">{([{ key: 'title', label: '실험 제목', max: 200 }, { key: 'purpose', label: '검토 목적', max: 4000 }, { key: 'description', label: '실험 상세 설명', max: 12000 }, { key: 'assumptions', label: '실험 가정 · 제약', max: 6000 }, { key: 'conclusion', label: '실험 결론', max: 6000 }] as const).map(({ key, label, max }) => <label key={key}>{label}<textarea className="input" aria-label={label} rows={key === 'description' ? 3 : 1} maxLength={max} value={draft[key]} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} /></label>)}
          <label>공개 범위<select aria-label="실험 공개 범위" value={draft.visibility} onChange={(e) => setDraft({ ...draft, visibility: e.target.value as 'private' | 'shared' })}><option value="private">개인 · 인증 사용자 본인</option><option value="shared">공유 · 인증된 사용자 열람</option></select></label>
          <p className="faint">개인 구분은 서버 사용자 인증이 활성화된 환경에서 적용됩니다.</p>
          <div><button className="btn primary" disabled={busy || !draft.title.trim()} onClick={save}>실험 저장</button></div>
        </div>
      </Card>}
      <Card id="wi-list" title="내 실험 · 공유 실험" note="저장된 조건을 불러와 현재 입력으로 다시 계산할 수 있습니다." defaultWide>
        <p className="faint">개인 구분은 서버 사용자 인증이 활성화된 환경에서 적용됩니다. 공유 실험은 인증된 사용자가 열람할 수 있습니다.</p>
        {savedQ.error && <div className="err">{savedQ.error} · 작성자 확인이 필요하면 설정에서 API 키를 연결하세요.</div>}
        {savedQ.loading ? <div className="faint">실험 불러오는 중…</div> : savedQ.data && <>
          <table className="tb-mini-table" style={{ width: '100%' }}><thead><tr><th>실험</th><th>공개</th><th>작성자 · 저장 시각</th><th /></tr></thead><tbody>{savedQ.data.items.map((experiment) => <tr key={experiment.id}><td>{experiment.title}<div className="faint">{experiment.purpose}</div></td><td>{experiment.visibility === 'private' ? '개인' : '공유'}</td><td>{experiment.created_by} · {date(experiment.created_at)}</td><td><button className="btn tb-mini" disabled={busy} onClick={() => reopen(experiment.id)}>조건 불러오기</button></td></tr>)}</tbody></table>
          {!savedQ.data.items.length && <p className="faint">아직 저장된 실험이 없습니다.</p>}
          <div className="toolbar"><button className="btn tb-mini" disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>이전 실험</button><span className="faint">총 {savedQ.data.total}건</span><button className="btn tb-mini" disabled={busy || !savedQ.data.has_next} onClick={() => setOffset(offset + 20)}>다음 실험</button></div>
        </>}
      </Card>
    </div>
    {busy && <p role="status">계산 중…</p>}{message && <p role="status" className={stale ? 'err' : ''}>{message}</p>}
  </>
}
/** The answer first: verdict + one sentence + facts, then what the LLM read (if a question was asked). */
function AnswerView({ resp, asked, dirty, busy, onAction, onChoose }: { resp: AskResponse; asked: string; dirty: boolean; busy: boolean
  onAction: (a: NonNullable<AskResponse['answer']>['actions'][number]) => void; onChoose: (change: WhatIfChange) => void }) {
  const a = resp.answer, i = resp.interpretation
  if (!a && (!i || i.status === 'llm_unavailable')) return null
  return <Card id="wi-answer" title="답변" note={asked ? `“${asked}”` : undefined} defaultWide>
    {dirty && <p className="faint">조건이 바뀌었습니다 — “답 보기”로 다시 계산하세요.</p>}
    {a && <>
      <p className="wi-headline"><span className={`badge ${VERDICT[a.verdict]?.cls ?? ''}`}>{VERDICT[a.verdict]?.label ?? a.verdict}</span> <b>{a.headline}</b></p>
      {a.facts.length > 0 && <ul className="wi-answer">{a.facts.map((f) => <li key={f} className={f.startsWith('미달') ? 'warn' : ''}>{f}</li>)}</ul>}
      {a.actions.length > 0 && <div className="toolbar" style={{ flexWrap: 'wrap' }}><span className="faint">이어서</span>{a.actions.map((x) => <button key={x.label} className="btn tb-mini" disabled={busy} onClick={() => onAction(x)}>{x.label}</button>)}</div>}
    </>}
    {i && i.status !== 'llm_unavailable' && <div className="wi-interp-box">
      <p className="faint">사내 LLM 해석{i.model ? ` · ${i.model}` : ''}{i.latency_ms != null ? ` · ${i.latency_ms} ms` : ''} → 위 조건 선택에 채웠습니다. 고쳐서 다시 계산할 수 있습니다.</p>
      {i.notes?.map((n) => <p className="faint" key={n}>{n}</p>)}
      {i.clarification && <div className="wi-clarify"><p>{i.clarification.message}</p>
        <div className="toolbar" style={{ flexWrap: 'wrap' }}>{i.clarification.choices.map((c) => <button key={c.label} className="btn tb-mini" disabled={busy} onClick={() => onChoose(c.change)}>{c.label}</button>)}</div></div>}
      {i.status === 'unsupported' && <p className="err">계산할 조건을 찾지 못했습니다 — 위에서 조건을 직접 고르세요.</p>}
      {i.ignored?.length ? <div className="wi-ignored"><b>계산에 넣지 않은 부분</b><ul>{i.ignored.map((x) => <li key={x.text + x.reason}>“{x.text}” — {x.reason}</li>)}</ul></div> : null}
    </div>}
  </Card>
}
function SearchView({ rows }: { rows: NonNullable<AskResponse['search']> }) {
  return <Card id="wi-search" title="Level 한계 탐색" note="한 단계씩 낮추며 Timing Budget 판정 — 처음 미달인 level에서 멈춤" defaultWide>
    {rows.map((r) => <div key={r.domain} className="table-x"><p><b>{r.domain}</b> <span className="faint">현재 L{r.level} · {r.mhz} MHz · {r.ips.join(', ')}</span></p>
      {r.at_min ? <p className="faint">이미 최저 OPP입니다.</p> : <table className="tb-mini-table" style={{ width: '100%' }}><thead><tr><th>level</th><th>MHz</th><th>판정</th><th>모델 전력 Δ mW</th><th>최소 여유 ms</th><th>미달 사유</th></tr></thead>
        <tbody>{r.rows.map((x) => <tr key={x.level} className={x.feasible ? '' : 'wi-fail'}><th>L{x.level}</th><td className="mono">{x.mhz}</td><td>{x.feasible ? '충족' : '미달'}</td>
          <td className="mono">{x.delta_mw != null ? fmt(x.delta_mw, 1) : '—'}</td><td className="mono">{x.min_slack_ms != null ? `${fmt(x.min_slack_ms, 2)} (${x.tight_stage})` : '—'}</td><td>{x.reason ?? ''}</td></tr>)}</tbody></table>}
    </div>)}
  </Card>
}
function DiagnoseView({ diag }: { diag: NonNullable<AskResponse['diagnose']> }) {
  return <Card id="wi-diag" title="구간별 여유 · 병목" note={`frame period ${fmt(diag.period_ms, 2)} ms · 여유 = 현재 clock에서 남는 시간`} defaultWide>
    <table className="tb-mini-table" style={{ width: '100%' }}><thead><tr><th>구간</th><th>여유 ms</th><th>사용률</th><th>HW ms</th><th>SW ms</th></tr></thead>
      <tbody>{diag.stages.map((st) => <tr key={st.id} className={st.id === diag.tight?.id ? 'wi-focus' : ''}><th>{st.name}</th><td className="mono">{fmt(st.slack_ms, 2)}</td><td className="mono">{st.fill_pct != null ? `${fmt(st.fill_pct, 0)}%` : '—'}</td><td className="mono">{fmt(st.hw_ms, 2)}</td><td className="mono">{fmt(st.sw_ms, 2)}</td></tr>)}</tbody></table>
    <table className="tb-mini-table" style={{ width: '100%' }}><thead><tr><th>DVFS domain</th><th>현재</th><th>낮출 여지</th><th>올릴 여지</th><th>IP</th></tr></thead>
      <tbody>{diag.domains.map((d) => <tr key={d.id}><th>{d.id}</th><td>L{d.level} · {d.mhz} MHz</td><td>{d.down ? `${d.down}단계` : '최저 OPP'}</td><td>{d.up ? `${d.up}단계` : '최고 OPP'}</td><td>{d.ips.join(', ')}</td></tr>)}</tbody></table>
    {diag.notes.map((n) => <p className="faint" key={n}>{n}</p>)}
  </Card>
}
/** Editor driven by the change kind's metadata; DVFS level picks from the domain's OPP ladder. */
function ChangeEditor({ change, kinds, targets, disabled, onChange, onRemove }: { change: WhatIfChange; kinds: ChangeKindMeta[]; targets: WhatIfTargets; disabled: boolean; onChange: (next: WhatIfChange) => void; onRemove: () => void }) {
  const kind = kinds.find((k) => k.target === change.target)
  const label = kind?.label ?? change.target
  const selector = kind?.selector ?? null
  const node = change.node_id ? targets.nodes.find((n) => n.id === change.node_id) : undefined
  const choiceText = (row: ChangeKindMeta['choices'][number]) => {
    if (kind?.shape === 'level') return `${row.id} · 현재 L${row.level} ${row.mhz} MHz${row.ips?.length ? ` · ${row.ips.join(', ')}` : ''}`
    const clock = kind?.target === 'node_clock_mhz' ? targets.nodes.find((n) => n.id === row.id)?.clock_mhz : null
    return [row.id, row.size ? row.size.join('×') : null, row.label, row.role === 'record' ? '녹화' : row.role === 'preview' ? '미리보기' : null, row.ip && row.ip !== row.id ? row.ip : null, clock ? `현재 ${clock} MHz` : null].filter(Boolean).join(' · ')
  }
  const domain = kind?.shape === 'level' ? kind.choices.find((c) => c.id === change.domain) : undefined
  const ladder = domain?.ladder ?? []
  const cur = ladder.findIndex((lv) => lv.level === domain?.level)
  const valueLabel = change.target === 'fps' ? 'FPS' : change.target === 'node_clock_mhz' ? 'MHz' : kind?.unit || '값'
  const valueAria = change.target === 'fps' ? '변경 FPS' : change.target === 'node_clock_mhz' ? '변경 clock MHz' : `변경 ${label}`
  return <fieldset className="wi-change" disabled={disabled}><legend title={kind?.description}>{label}</legend>
    {selector && <label>대상<select aria-label={`${label} 대상`} value={change[selector] ?? ''} onChange={(e) => {
      const choice = kind?.choices.find((row) => row.id === e.target.value)
      const next: WhatIfChange = { ...change, [selector]: e.target.value || undefined, ...(kind?.needs_param && choice?.param ? { param: choice.param } : {}) }
      if (kind?.shape === 'level' && choice?.ladder) { const at = choice.ladder.findIndex((lv) => lv.level === choice.level); next.level = choice.ladder[Math.max(0, at - 1)]?.level ?? choice.level ?? 0 }
      onChange(next)
    }}><option value="">{kind?.selector_optional ? '자동 (단일 대상)' : '대상 선택'}</option>{(kind?.choices ?? []).map((row) => <option key={`${row.id}-${row.param ?? ''}`} value={row.id}>{choiceText(row)}</option>)}</select></label>}
    {kind?.shape === 'level' ? <label>level<select aria-label={`${change.domain ?? ''} level`} value={change.level ?? ''} onChange={(e) => onChange({ ...change, level: Number(e.target.value) })}>
      {ladder.map((lv, j) => <option key={lv.level} value={lv.level}>L{lv.level} · {lv.mhz} MHz{j === cur ? ' (현재)' : j < cur ? ` (−${cur - j})` : ` (+${j - cur})`}</option>)}</select></label>
      : kind?.shape === 'size' || (!kind && change.width != null)
        ? <><label>너비<input className="input" aria-label="변경 너비" type="number" min={16} max={16384} step={1} value={change.width ?? ''} onChange={(e) => onChange({ ...change, width: Number(e.target.value) })} /></label><label>높이<input className="input" aria-label="변경 높이" type="number" min={16} max={16384} step={1} value={change.height ?? ''} onChange={(e) => onChange({ ...change, height: Number(e.target.value) })} /></label>
          <span className="wi-presets">{SIZE_PRESETS.map(([name, w, h]) => <button key={name} type="button" className={`btn tb-mini ${change.width === w && change.height === h ? 'on' : ''}`} onClick={() => onChange({ ...change, width: w, height: h })}>{name}</button>)}</span></>
        : <><label>{valueLabel}<input className="input" aria-label={valueAria} type="number" min={1} max={kind?.max_value ?? undefined} value={change.value ?? ''} onChange={(e) => onChange({ ...change, value: Number(e.target.value) })} /></label>
          {change.target === 'fps' && <span className="wi-presets">{FPS_PRESETS.map((v) => <button key={v} type="button" className={`btn tb-mini ${change.value === v ? 'on' : ''}`} onClick={() => onChange({ ...change, value: v })}>{v}</button>)}</span>}
          {change.target === 'node_clock_mhz' && node?.clock_mhz && <span className="wi-presets">{[-20, -10, 10, 20].map((p) => <button key={p} type="button" className="btn tb-mini" onClick={() => onChange({ ...change, value: Math.round(node.clock_mhz! * (1 + p / 100) * 10) / 10 })}>{p > 0 ? '+' : ''}{p}%</button>)}
            <span className="faint">현재 {node.clock_mhz} MHz · 하한이므로 현재보다 낮추면 효과 없음{node.dvfs_group ? ` (낮추려면 DVFS level ${node.dvfs_group})` : ''}</span></span>}</>}
    <button type="button" className="btn tb-mini" onClick={onRemove}>항목 제거</button>
  </fieldset>
}
const FOCUS_ROWS: Record<FocusMetric, string[]> = { power: ['modeled_power_mw', 'cpu_power_mw', 'ip_power_mw', 'memory_power_mw'], bw: ['bw_mbs', 'memory_power_mw'], timing: ['period_ms', 'fps'], clock: [], feasible: [] }
function ResultView({ result, focus }: { result: WhatIfResult; focus: FocusMetric[] }) {
  const before = result.baseline, after = result.candidate
  const hot = new Set(focus.flatMap((key) => FOCUS_ROWS[key]))
  const metrics = [{ key: 'modeled_power_mw', label: '모델 합계', unit: 'mW' }, { key: 'cpu_power_mw', label: 'CPU', unit: 'mW' }, { key: 'ip_power_mw', label: 'IP', unit: 'mW' }, { key: 'memory_power_mw', label: '메모리 BW', unit: 'mW' }, { key: 'bw_mbs', label: 'BW', unit: 'MB/s' }, { key: 'fps', label: 'FPS', unit: 'fps' }, { key: 'period_ms', label: 'Frame period', unit: 'ms' }] as const
  const baseIps = new Map(before.report.ips.map((ip) => [ip.node, ip]))
  const explanations = new Map(result.delta.ips.map((ip) => [ip.node, ip.explanation]))
  const baseStages = new Map(before.report.stages.map((stage) => [stage.id, stage]))
  const delta = (a: number, b: number) => `${b - a >= 0 ? '+' : ''}${fmt(b - a, 2)}`
  return <>
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
