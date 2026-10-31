// Behavior: extra scenario information from a full-stack trace (App · Framework · HAL · Kernel · FW · HW slices
// with hand-off flows). Simulation inputs stay on the Pipeline page; this page explains them.
//   Full-stack timing — the whole stack on one diagram, one vertical scroll, Perfetto-style keys
//   Cadence           — which work runs at which rate and which cadences hand off to each other
//   Processing flow   — each unit's cross-layer hand-off order and its loop (sdb.handoff/1 document, else the selected chain)
import { useMemo, useState } from 'react'
import type { Ctx } from '../App'
import { api, type BehaviorEntry, type Evidence, type HandoffDoc } from '../lib/api'
import { useAsync } from '../lib/route'
import { buildTimeline, chainOf, FRAME_HUES, FULLSTACK_GROUPS, INDEPENDENT_STYLE, isFullStack, LAYER_COLORS, type Slice, type Timeline } from '../lib/timeline'
import { TimelineView, type FlowMode } from '../components/TimelineView'
import { HandoffView } from '../components/HandoffView'
import { cadenceLabel, cadencePeriod, deriveHandoff, layerColor, loopKind, type ColumnMode } from '../lib/handoff'
import { Sec, Shell } from '../components/MeasurePopover'
import { PageLayout, usePref } from '../components/Layout'

type Tab = 'fullstack' | 'cadence' | 'flow'
const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: 'fullstack', label: 'Full-stack timing', hint: 'App부터 HW까지 실제 실행 순서. 계층(group) 이름을 눌러 접고, slice를 누르면 그 chain만 화살표로 남습니다.' },
  { id: 'cadence', label: 'Cadence', hint: '어떤 일이 어떤 주기로 도는지, 서로 다른 주기끼리 어디서 넘겨주는지. 창 밖의 느린 일(chunk write, UI)도 자기 주기로 표시합니다.' },
  { id: 'flow', label: 'Processing flow', hint: '한 단위(frame · buffer · 주기)가 계층을 건너가는 순서, 단계마다의 대기 시간(Δ), 그리고 어느 loop로 반복되는지. 행을 누르면 Full-stack timing에서 엽니다.' },
]

export function BehaviorPage({ ctx }: { ctx: Ctx }) {
  const { scenario, variant } = ctx
  const tab: Tab = (['fullstack', 'cadence', 'flow'] as Tab[]).includes(ctx.params.tab as Tab) ? (ctx.params.tab as Tab) : 'fullstack'
  const setTab = (t: Tab) => ctx.navigate(undefined, { tab: t }, true)
  const evQ = useAsync(() => (variant ? api.evidenceList(scenario, variant, ctx.project) : Promise.resolve({ items: [], total: 0 })), [scenario, variant, ctx.project])
  const traces = useMemo(() => (evQ.data?.items ?? []).filter((e) => isFullStack(e.timeline_events) || !!e.handoff_flows), [evQ.data])
  const [traceId, setTraceId] = useState('')
  const trace: Evidence | undefined = traces.find((t) => t.id === traceId) ?? traces[0]
  const timeline = useMemo(() => (trace && isFullStack(trace.timeline_events) ? buildTimeline(trace.timeline_events ?? [], { maxFrames: 64, groupOrder: FULLSTACK_GROUPS }) : null), [trace])
  const [columnMode, setColumnMode] = usePref<ColumnMode>('behavior.flow.columns', 'layer')
  const [flowMode, setFlowMode] = usePref<FlowMode>('behavior.flow', 'chain')
  const [colorBy, setColorBy] = usePref<'group' | 'frame'>('behavior.color', 'frame')
  const selectedId = ctx.params.slice && timeline?.slices.some((s) => s.id === ctx.params.slice) ? ctx.params.slice : null
  const select = (s: Slice | null) => ctx.navigate(undefined, { slice: s?.id }, true)
  const selected = selectedId ? timeline?.slices.find((s) => s.id === selectedId) ?? null : null
  const info = TABS.find((t) => t.id === tab)!

  const top = (
    <div className="toolbar">
      <div className="seg" role="tablist" aria-label="Behavior 보기">
        {TABS.map((t) => <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'on' : ''} onClick={() => setTab(t.id)} title={t.hint}>{t.label}</button>)}
      </div>
      {traces.length > 1 && <select value={trace?.id ?? ''} onChange={(e) => { setTraceId(e.target.value); ctx.navigate(undefined, { slice: undefined, flow: undefined }, true) }} aria-label="full-stack trace" style={{ minWidth: 0, flex: '0 1 340px' }}>
        {traces.map((t) => <option key={t.id} value={t.id}>{t.id}</option>)}</select>}
      {traces.length === 1 && trace && <span className="chip" title="full-stack trace evidence">{trace.id}</span>}
      {tab === 'fullstack' && timeline && <>
        <div className="seg sm" role="group" aria-label="화살표">
          {([['chain', '선택 chain'], ['frame', '같은 frame'], ['all', '모두'], ['none', '없음']] as [FlowMode, string][]).map(([k, l]) =>
            <button key={k} className={flowMode === k ? 'on' : ''} onClick={() => setFlowMode(k)}>{l}</button>)}
        </div>
        <select value={colorBy} onChange={(e) => setColorBy(e.target.value as 'group' | 'frame')} aria-label="색 기준">
          <option value="frame">색: frame</option><option value="group">색: 계층</option></select>
        <ColorLegend by={colorBy} />
      </>}
      <span className="grow" />
      <span className="faint" style={{ fontSize: 12, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={info.hint}>{info.hint}</span>
    </div>
  )

  let main
  if (!variant) main = <div className="empty">Variant를 선택하세요.</div>
  else if (evQ.error) main = <div className="err">{evQ.error}</div>
  else if (evQ.loading) main = <div className="empty">Evidence 불러오는 중…</div>
  else if (!trace) main = <NoBehavior ctx={ctx} />
  else if (tab === 'flow') {
    const doc = trace.handoff_flows ?? (timeline ? deriveHandoffOrNull(timeline, selected) : null)
    main = (
      <section className="panel pane behavior-pane"><div className="pane-body" style={{ overflow: 'auto' }}>
        {doc ? <HandoffView doc={doc} flowId={ctx.params.flow ?? null} onFlow={(id) => ctx.navigate(undefined, { flow: id }, true)} mode={columnMode} onMode={setColumnMode}
          source={trace.handoff_flows ? `hand-off 문서 (${trace.handoff_flows.generator ?? 'sdb.handoff/1'})` : '선택 slice의 chain (trace에서 유도)'}
          canOpen={(id) => !!timeline?.slices.some((s) => s.id === id)} onOpen={(id) => ctx.navigate(undefined, { tab: 'fullstack', slice: id }, true)} />
          : <div className="empty">Processing flow를 볼 slice가 없습니다.</div>}
      </div></section>
    )
  }
  else if (!timeline) main = <div className="empty">이 evidence에는 full-stack timeline이 없고 hand-off 순서만 있습니다. Processing flow 탭에서 보세요.</div>
  else if (tab === 'fullstack') main = (
    <section className="panel pane behavior-pane">
      <TimelineView timeline={timeline} selectedSlice={selectedId} highlightNode={null} showFlows flowMode={flowMode} colorBy={colorBy}
        labelWidth={220} autoFocus groupColor={layerColor} onSelect={select} />
      <SelectionLine timeline={timeline} selected={selected} flowMode={flowMode} />
    </section>
  )
  else main = <section className="panel pane behavior-pane"><div className="pane-body" style={{ overflow: 'auto' }}>
    <CadenceTab timeline={timeline} doc={trace.handoff_flows} onOpenSlice={(id) => ctx.navigate(undefined, { tab: 'fullstack', slice: id }, true)}
      onOpenFlow={(id) => ctx.navigate(undefined, { tab: 'flow', flow: id }, true)} /></div></section>
  return <PageLayout id="behavior" top={top} main={main} />
}

/** Empty state: say how the page gets filled and link the variants that already have Behavior data. */
function NoBehavior({ ctx }: { ctx: Ctx }) {
  const idx = useAsync(() => api.behaviorIndex(ctx.project).catch(() => []), [ctx.project])
  const here = (idx.data ?? []).filter((e) => e.scenario_ref === ctx.scenario)
  const others = (idx.data ?? []).filter((e) => e.scenario_ref !== ctx.scenario)
  const link = (e: BehaviorEntry) => <a key={`${e.scenario_ref}/${e.variant_ref}`} href="#" className="chip" onClick={(ev) => { ev.preventDefault(); ctx.navigate(undefined, { scenario: e.scenario_ref, variant: e.variant_ref, slice: undefined, flow: undefined }) }}>
    {e.scenario_ref === ctx.scenario ? '' : `${e.scenario_ref} · `}{e.variant_ref}</a>
  return <div className="empty" style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-start' }}>
    <span>이 variant에는 Behavior data가 없습니다. 계층(layer)이 붙은 full-stack timeline이나 hand-off 순서(sdb.handoff/1)를 가진 측정 evidence를 import하면 채워집니다 (scenario_db.meas_import fullstack --handoff).</span>
    {here.length > 0 && <span style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>같은 scenario의 등록 variant: {here.map(link)}</span>}
    {others.length > 0 && <span style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>다른 scenario: {others.map(link)}</span>}
  </div>
}

/** What the slice colours mean (frame mode: hue = frame; group mode: one hue per layer). */
function ColorLegend({ by }: { by: 'group' | 'frame' }) {
  const box = (fill: string, stroke?: string, hatch = false) => <svg width="14" height="10"><rect x="0.5" y="0.5" width="13" height="9" rx="2" fill={fill} stroke={stroke ?? 'none'} />
    {hatch && <path d="M2 9 L9 1 M7 9 L13 3" stroke="rgba(31,36,48,.35)" strokeWidth="1" />}</svg>
  if (by === 'group') return <span className="legend-mini" style={{ flex: '0 1 auto' }}>
    {FULLSTACK_GROUPS.map((g) => <span key={g} className="legend-item">{box(LAYER_COLORS[g].fill, LAYER_COLORS[g].strong)}{g}</span>)}</span>
  return <span className="legend-mini" style={{ flex: '0 1 auto' }} title="hue = frame (f0 · f1 · f2 …) · 진한 색 = HW, 옅은 색 = SW 계층 · 회색 빗금 = 자기 주기(frame에 속하지 않음)">
    <span className="legend-item">{FRAME_HUES.slice(0, 4).map((h) => <span key={h} style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: `hsl(${h} 62% 70%)`, marginRight: 1 }} />)} frame</span>
    <span className="legend-item">{box('hsl(212 70% 48%)')}HW</span><span className="legend-item">{box('hsl(212 62% 76%)')}SW</span>
    <span className="legend-item">{box(INDEPENDENT_STYLE.fill, INDEPENDENT_STYLE.stroke, true)}자기 주기</span></span>
}

/** One status line under the diagram instead of a details card. */
function SelectionLine({ timeline, selected, flowMode }: { timeline: Timeline; selected: Slice | null; flowMode: FlowMode }) {
  if (!selected) return <div className="behavior-status faint">slice를 누르면 선택 정보가 여기 표시됩니다 · 계층 이름 클릭 = 접기</div>
  const chain = chainOf(timeline, selected.id)
  const items = timeline.slices.filter((s) => chain.has(s.id))
  const a = Math.min(...items.map((s) => s.start)), b = Math.max(...items.map((s) => s.end))
  const track = timeline.groups.flatMap((g) => g.tracks).find((t) => t.id === selected.track)
  return (
    <div className="behavior-status">
      <b>{selected.label}</b>{selected.nodeId && <span className="chip" title="Pipeline timing에 나오는 node">node {selected.nodeId}</span>}
      <span>{selected.group} · {track?.name}</span>
      <span className="mono">{selected.start.toFixed(2)} → {selected.end.toFixed(2)} ms ({(selected.end - selected.start).toFixed(2)})</span>
      {selected.frame !== null ? <span className="mono">f{selected.frame}</span> : selected.period ? <span className="mono">자기 주기 {selected.period.toFixed(1)} ms</span> : null}
      <span className="faint">chain {chain.size - 1}단계 · {(b - a).toFixed(1)} ms{flowMode !== 'chain' ? ' (화살표: 선택 chain에서 표시)' : ''}</span>
    </div>
  )
}

/// ---------------------------------------------------------------- Cadence
type PeriodBasis = 'doc' | 'trace' | 'frame' | 'window' | 'borrowed'
export interface CadRow {
  name: string; group: string; track: string; node: string | null; n: number; dur: number; min: number; max: number
  period: number | null; frameLocked: boolean; load: number | null
  /** where the period comes from: hand-off document, trace-wide capture, frame gap, window gaps, or borrowed frame period */
  basis: PeriodBasis; cadence: string | null; ids: string[]
}
const BASIS_TEXT: Record<PeriodBasis, string> = {
  doc: 'hand-off 문서에 선언된 loop 주기',
  trace: 'import 때 전체 capture에서 잰 시작 간격의 중앙값 (cadence_period_ms)',
  frame: 'frame 경로: 같은 task의 frame 간 시작 간격',
  window: '창 안 시작 간격의 중앙값 (창이 짧으면 부정확)',
  borrowed: '창 안에서 한 번만 보임 → frame 주기를 빌려 씀',
}

/** Declared loop of each common name in a hand-off document (step cadence, else its flow's). */
export function declaredCadences(doc: HandoffDoc | null | undefined): Map<string, { id: string; period: number | null; frame: boolean }> {
  const out = new Map<string, { id: string; period: number | null; frame: boolean }>()
  for (const f of doc?.flows ?? []) for (const s of f.steps) {
    if (!s.task || out.has(s.task)) continue
    const id = s.cadence ?? f.cadence
    out.set(s.task, { id, period: cadencePeriod(doc!, id), frame: doc!.cadences.find((c) => c.id === id)?.kind === 'frame' })
  }
  return out
}

export function cadenceRows(tl: Timeline, doc?: HandoffDoc | null): CadRow[] {
  const declaredDoc = declaredCadences(doc)
  const byName = new Map<string, Slice[]>()
  for (const s of tl.slices) byName.set(s.label, [...(byName.get(s.label) ?? []), s])
  const trackName = new Map(tl.groups.flatMap((g) => g.tracks).map((t) => [t.id, t.name]))
  const median = (v: number[]) => (v.length ? [...v].sort((x, y) => x - y)[Math.floor(v.length / 2)] : null)
  const gapsOf = (ss: Slice[]) => ss.slice(1).map((s, i) => s.start - ss[i].start)
  // frame period = median start gap of frame-locked tasks seen more than once (a task seen once borrows it)
  const framePeriod = median([...byName.values()].filter((ss) => !ss.some((s) => s.period) && ss.some((s) => s.frame !== null) && ss.length > 1)
    .map((ss) => median(gapsOf([...ss].sort((x, y) => x.start - y.start)))!))
  return [...byName.entries()].map(([name, ss]) => {
    ss.sort((x, y) => x.start - y.start)
    const fromDoc = declaredDoc.get(name)
    const declared = ss.find((s) => s.period)?.period ?? null
    const windowGap = median(gapsOf(ss))
    let period: number | null, basis: PeriodBasis, frameLocked: boolean
    if (fromDoc?.period) { period = fromDoc.period; basis = 'doc'; frameLocked = fromDoc.frame }
    else if (declared) { period = declared; basis = 'trace'; frameLocked = false }
    else {
      frameLocked = ss.some((s) => s.frame !== null)
      period = windowGap ?? (frameLocked ? framePeriod : null)
      basis = windowGap !== null ? (frameLocked ? 'frame' : 'window') : 'borrowed'
    }
    const durs = ss.map((s) => s.end - s.start)
    const dur = durs.reduce((a, b) => a + b, 0) / durs.length
    const sw = ss[0].group !== 'HW'
    return { name, group: ss[0].group, track: trackName.get(ss[0].track) ?? '', node: ss[0].nodeId, n: ss.length, dur, min: Math.min(...durs), max: Math.max(...durs),
      period, frameLocked, basis, cadence: fromDoc?.id ?? null, ids: ss.map((s) => s.id),
      load: period ? (sw ? dur * (1000 / period) : (dur * (1000 / period)) / 10) : null }
  }).sort((a, b) => (b.period ? 1000 / b.period : 0) - (a.period ? 1000 / a.period : 0) || FULLSTACK_GROUPS.indexOf(a.group) - FULLSTACK_GROUPS.indexOf(b.group))
}

const hz = (p: number | null) => (p ? 1000 / p : null)
const fmtHz = (v: number | null) => (v === null ? '—' : v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toFixed(2))
const classKey = (r: CadRow) => (r.frameLocked ? 'frame' : r.period ? fmtHz(hz(r.period)) : '?')
const loadText = (r: CadRow) => (r.load === null ? '—' : r.group === 'HW' ? `duty ${r.load.toFixed(1)} %` : `CPU ${r.load.toFixed(1)} ms/s`)
type CadClass = { key: string; rs: CadRow[]; rate: number | null; frame: boolean }
type Pop = { at: { x: number; y: number } } & ({ row: CadRow } | { cls: CadClass })

export function CadenceTab({ timeline, doc, onOpenSlice, onOpenFlow }: { timeline: Timeline; doc?: HandoffDoc | null; onOpenSlice: (id: string) => void; onOpenFlow: (id: string) => void }) {
  const rows = useMemo(() => cadenceRows(timeline, doc), [timeline, doc])
  const [pop, setPop] = useState<Pop | null>(null)
  const classes = useMemo(() => {
    const m = new Map<string, CadRow[]>()
    for (const r of rows) m.set(classKey(r), [...(m.get(classKey(r)) ?? []), r])
    return [...m.entries()].map(([key, rs]) => ({ key, rs, rate: hz(rs[0].period), frame: key === 'frame' }))
  }, [rows])
  const links = useMemo(() => {
    const cls = new Map(rows.map((r) => [r.name, classKey(r)]))
    const label = new Map(timeline.slices.map((s) => [s.id, s.label]))
    const m = new Map<string, number>()
    for (const f of timeline.flows) {
      const a = cls.get(label.get(f.from) ?? ''), b = cls.get(label.get(f.to) ?? '')
      if (a && b && a !== b) m.set(`${a}>${b}`, (m.get(`${a}>${b}`) ?? 0) + 1)
    }
    return [...m.entries()].map(([k, n]) => { const [a, b] = k.split('>'); return { a, b, n } })
  }, [rows, timeline])
  const at = (e: { clientX: number; clientY: number }) => ({ x: e.clientX, y: e.clientY })
  return (
    <div className="behavior-cadence">
      <CadenceMap classes={classes} links={links} onPick={(cls, e) => setPop({ cls, at: at(e) })} />
      <table className="grid cad-table">
        <thead><tr><th>주기</th><th>task (공통 name)</th><th>계층 · thread</th><th className="num">rate Hz</th><th>근거</th><th className="num">실행 ms</th><th className="num">부하</th><th className="num">창 안 횟수</th></tr></thead>
        <tbody>
          {classes.map((c) => c.rs.map((r, i) => (
            <tr key={r.name} className={i === 0 ? 'first' : ''} onClick={(e) => setPop({ row: r, at: at(e) })} title="클릭: 요약">
              {i === 0 && <td rowSpan={c.rs.length} className="cad-class" onClick={(e) => { e.stopPropagation(); setPop({ cls: c, at: at(e) }) }}>
                <b>{c.frame ? 'frame' : `${fmtHz(c.rate)} Hz`}</b><div className="faint">{c.frame ? 'frame 경로' : '자기 주기 · frame 경로 밖'}</div></td>}
              <td><span className="mono">{r.name}</span>{r.node && <span className="chip" style={{ marginLeft: 6 }} title="Pipeline timing에 나오는 node">{r.node}</span>}</td>
              <td><span className="layer-dot" style={{ background: layerColor(r.group) }} />{r.group} · {r.track}</td>
              <td className="num mono">{fmtHz(hz(r.period))}</td>
              <td><span className={`basis b-${r.basis}`} title={BASIS_TEXT[r.basis]}>{{ doc: '문서', trace: 'capture', frame: 'frame', window: '창 추정', borrowed: '차용' }[r.basis]}</span></td>
              <td className="num mono">{r.dur.toFixed(2)}</td>
              <td className="num mono">{loadText(r)}</td>
              <td className="num mono">{r.n}</td>
            </tr>)))}
        </tbody>
      </table>
      <p className="faint" style={{ fontSize: 12 }}>근거: 문서 = hand-off 문서가 선언한 loop · capture = import 때 전체 trace에서 잰 주기 · frame = frame 간 간격 · 창 추정 = 표시 창 안의 간격 (짧은 창에서는 부정확). 부하: SW = 실행 × rate (CPU ms/s), HW = 실행 × rate / 10 (duty %). 행이나 주기 칸을 누르면 요약이 열립니다.</p>
      {pop && <CadencePopover pop={pop} timeline={timeline} rows={rows} doc={doc} onClose={() => setPop(null)}
        onRow={(row, e) => setPop({ row, at: at(e) })} onOpenSlice={onOpenSlice} onOpenFlow={onOpenFlow} />}
    </div>
  )
}

function CadencePopover({ pop, timeline, rows, doc, onClose, onRow, onOpenSlice, onOpenFlow }: {
  pop: Pop; timeline: Timeline; rows: CadRow[]; doc?: HandoffDoc | null; onClose: () => void
  onRow: (r: CadRow, e: { clientX: number; clientY: number }) => void; onOpenSlice: (id: string) => void; onOpenFlow: (id: string) => void
}) {
  if ('cls' in pop) {
    const c = pop.cls
    const cpu = c.rs.filter((r) => r.group !== 'HW').reduce((a, r) => a + (r.load ?? 0), 0)
    const hw = c.rs.filter((r) => r.group === 'HW')
    return <Shell title={`${c.frame ? 'frame 경로' : `${fmtHz(c.rate)} Hz loop`} · task ${c.rs.length}`} at={pop.at} onClose={onClose} width={460}>
      <Sec title="요약"><div className="vp-kv">
        <span>주기</span><span>{c.rate ? `${fmtHz(c.rate)} Hz (${(1000 / c.rate).toFixed(2)} ms)` : '—'} · {c.frame ? 'frame에 묶여 반복' : 'frame과 독립적으로 반복'}</span>
        <span>CPU</span><span className="mono">{cpu.toFixed(1)} ms/s</span>
        <span>HW duty</span><span className="mono">{hw.length ? hw.map((r) => `${r.name} ${r.load?.toFixed(1) ?? '—'} %`).join(' · ') : '—'}</span>
      </div></Sec>
      <Sec title="task"><div className="cad-pop-list">{c.rs.map((r) => <button key={r.name} className="link-btn" onClick={(e) => onRow(r, e)}>
        <span className="layer-dot" style={{ background: layerColor(r.group) }} />{r.name} <span className="faint mono">{r.dur.toFixed(2)} ms</span></button>)}</div></Sec>
    </Shell>
  }
  const r = pop.row
  const ids = new Set(r.ids)
  const label = new Map(timeline.slices.map((s) => [s.id, s.label]))
  const cls = new Map(rows.map((x) => [x.name, x]))
  const ends = (pick: 'from' | 'to', other: 'from' | 'to') => [...new Set(timeline.flows.filter((f) => ids.has(f[pick])).map((f) => label.get(f[other]) ?? ''))].filter((n) => n && n !== r.name)
  const ins = ends('to', 'from'), outs = ends('from', 'to')
  const rate = (n: string) => { const x = cls.get(n); return x ? (x.frameLocked ? 'frame' : `${fmtHz(hz(x.period))} Hz`) : '' }
  const flows = (doc?.flows ?? []).filter((f) => f.steps.some((s) => s.task === r.name))
  const loop = r.cadence && doc ? `${cadenceLabel(doc, r.cadence)} · ${loopKind(doc, r.cadence)}` : null
  return <Shell title={<>{r.name}{r.node && <span className="chip" style={{ marginLeft: 6 }}>node {r.node}</span>}</>} at={pop.at} onClose={onClose} width={480}>
    <Sec title="주기"><div className="vp-kv">
      <span>rate</span><span className="mono">{fmtHz(hz(r.period))} Hz{r.period ? ` · ${r.period.toFixed(2)} ms` : ''}</span>
      <span>loop</span><span>{loop ?? (r.frameLocked ? 'frame에 묶여 반복' : r.period ? 'frame과 독립적인 자기 주기' : '—')}</span>
      <span>근거</span><span>{BASIS_TEXT[r.basis]}</span>
    </div></Sec>
    <Sec title="실행"><div className="vp-kv">
      <span>계층</span><span><span className="layer-dot" style={{ background: layerColor(r.group) }} />{r.group} · {r.track}</span>
      <span>실행 ms</span><span className="mono">mean {r.dur.toFixed(2)} · min {r.min.toFixed(2)} · max {r.max.toFixed(2)} (창 안 {r.n}회)</span>
      <span>부하</span><span className="mono">{loadText(r)}</span>
    </div></Sec>
    <Sec title="연결"><div className="vp-kv">
      <span>받는 곳</span><span>{ins.length ? ins.map((n) => `${n} (${rate(n)})`).join(' · ') : '— (loop 시작)'}</span>
      <span>넘기는 곳</span><span>{outs.length ? outs.map((n) => `${n} (${rate(n)})`).join(' · ') : '—'}</span>
    </div></Sec>
    <div className="cad-pop-actions">
      <button className="btn" onClick={() => onOpenSlice(r.ids[0])}>Full-stack timing에서 보기</button>
      {flows.map((f) => <button key={f.id} className="btn" onClick={() => onOpenFlow(f.id)}>Processing flow · {f.name}</button>)}
    </div>
  </Shell>
}

function CadenceMap({ classes, links, onPick }: { classes: CadClass[]; links: { a: string; b: string; n: number }[]; onPick: (c: CadClass, e: { clientX: number; clientY: number }) => void }) {
  const W = 920, left = 20, right = 20, top = 30, chipH = 24
  const lo = Math.log10(0.1), hi = Math.log10(1000)
  const lx = (v: number) => left + ((Math.log10(Math.min(1000, Math.max(0.1, v))) - lo) / (hi - lo)) * (W - left - right)
  const placed: { c: CadClass; x: number; w: number; lv: number; label: string }[] = []
  const levels: number[] = []
  for (const c of [...classes].filter((c) => c.rate).sort((a, b) => a.rate! - b.rate!)) {
    const label = `${c.frame ? 'frame ' : ''}${fmtHz(c.rate)} Hz · ${c.rs.length}`
    const w = label.length * 6.4 + 18
    const x = Math.min(W - right - w, Math.max(left, lx(c.rate!) - w / 2))
    let lv = 0
    while (levels[lv] !== undefined && levels[lv] > x - 6) lv++
    levels[lv] = x + w
    placed.push({ c, x, w, lv, label })
  }
  const H = top + Math.max(1, levels.length) * (chipH + 22) + 10
  const pos = new Map(placed.map((p) => [p.c.key, p]))
  return (
    <svg width={W} height={H} role="img" aria-label="Cadence map" style={{ display: 'block', maxWidth: '100%' }}>
      <defs><marker id="cad-ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8A8274" /></marker></defs>
      {[0.1, 1, 10, 100, 1000].map((v) => <g key={v}><line x1={lx(v)} x2={lx(v)} y1={top - 8} y2={H - 4} stroke="#EFEAE2" />
        <text x={lx(v)} y={14} fontSize={10.5} textAnchor="middle" fill="#6B6558" fontFamily="var(--mono)">{v} Hz</text></g>)}
      {links.map((l) => {
        const a = pos.get(l.a), b = pos.get(l.b)
        if (!a || !b) return null
        const ya = top + a.lv * (chipH + 22) + chipH / 2, yb = top + b.lv * (chipH + 22) + chipH / 2
        const xa = a.x + a.w / 2, xb = b.x + b.w / 2, my = Math.min(ya, yb) - 18
        // the count lives in the tooltip: arc labels collide when several loops sit close on the rate axis
        return <path key={`${l.a}>${l.b}`} d={`M${xa},${ya - chipH / 2} Q${(xa + xb) / 2},${my} ${xb},${yb - chipH / 2}`} fill="none" stroke="#8A8274" strokeWidth={1.1} markerEnd="url(#cad-ah)" opacity={0.8}>
          <title>{`${a.label} → ${b.label}: ${l.n} hand-off`}</title></path>
      })}
      {placed.map((p) => (
        <g key={p.c.key} style={{ cursor: 'pointer' }} onClick={(e) => onPick(p.c, e)}>
          <title>클릭: 이 주기의 요약</title>
          <rect x={p.x} y={top + p.lv * (chipH + 22)} width={p.w} height={chipH} rx={12} fill={p.c.frame ? '#E3EEEB' : '#fff'} stroke={p.c.frame ? '#2F6F68' : '#A8A091'} strokeDasharray={p.c.frame ? undefined : '4 3'} />
          <text x={p.x + 9} y={top + p.lv * (chipH + 22) + 16} fontSize={11} fill="#1F2430">{p.label}</text>
        </g>))}
    </svg>
  )
}

// ---------------------------------------------------------------- Processing flow

function defaultSeed(tl: Timeline): Slice | null {
  // last Pipeline node of the earliest complete frame (e.g. encoder / writer), else the first slice
  const frames = tl.frames
  const f = frames[Math.min(1, frames.length - 1)]
  const cands = tl.slices.filter((s) => s.frame === f && s.nodeId)
  return cands.sort((a, b) => b.end - a.end)[0] ?? tl.slices[0] ?? null
}

function deriveHandoffOrNull(tl: Timeline, selected: Slice | null) {
  const seed = selected ?? defaultSeed(tl)
  return seed ? deriveHandoff(tl, seed) : null
}
