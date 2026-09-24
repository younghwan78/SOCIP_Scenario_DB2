import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Ctx } from '../App'
import { api, type Evidence } from '../lib/api'
import { useAsync } from '../lib/route'
import { buildGraph, layoutGraph, memoryText, pipelineIdOf, type Layout } from '../lib/graph'
import { buildTimeline, type Slice } from '../lib/timeline'
import { evidenceSource } from '../lib/conditions'
import { buildModel, LANE_LABEL, type BufferRow, type IpModel } from '../lib/model'
import { sequenceLayout } from '../lib/sequence'
import { stageTimings, type StageTiming } from '../lib/cadence'
import { modeNotes } from '../lib/modes'
import { GraphView } from '../components/GraphView'
import { TimelineView } from '../components/TimelineView'
import { IpInternalView } from '../components/IpInternalView'
import { CadenceView } from '../components/CadenceView'
import { DataTable, type Column } from '../components/DataTable'
import { useWidth } from '../components/Charts'
import { rememberRecent } from '../components/Picker'
import { PageLayout, Resizer, usePref } from '../components/Layout'

type Lens = 'sequence' | 'dma' | 'ip'
type Mode = 'split' | 'graph' | 'timing'
type TimingView = 'trace' | 'cadence'

const LENS: { id: Lens; label: string; hint: string }[] = [
  { id: 'sequence', label: 'Sequence · HW/SW 순서', hint: 'Sensor → Panel/Storage 실행 순서. 같은 열 = OTF streaming(같은 시점), 다음 열 = M2M 또는 SW hand-off. RT 이후 어떤 SW가 NRT를 열고, NRT 이후 어떤 SW가 출력단을 여는지 확인. 노드: +frame 기준 시작 · 소요(ms) / 처리 크기' },
  { id: 'dma', label: 'DMA · Memory', hint: 'Buffer 중심: IP WDMA → Buffer → RDMA. W×H · format · bit · 압축 · MB/frame · MB/s, IP 입력→출력 크기, history(f-1) · stat · optional DMA 포함. 상세 값은 하단 DMA 표' },
  { id: 'ip', label: 'IP 내부', hint: 'IP 하나의 OTF in / RDMA / history read → Core(처리 크기, crop·scale·mode) → OTF out / WDMA / stat 출력. 입력 대비 출력 scale 비율 표시' },
]
const legacyLens = (l?: string): Lens => (l === 'topology' ? 'sequence' : l === 'transform' ? 'ip' : l === 'dma' || l === 'ip' || l === 'sequence' ? l : 'sequence')
const OUT_NODES = /^(panel|dpu|mfc|apv)/

function rankTrace(e: Evidence): number {
  const t = e.timeline_events ?? []
  const frames = new Set(t.map((x) => x.frame_index)).size
  const outputs = t.some((x) => OUT_NODES.test(String(x.node_id ?? '')))
  return (outputs ? 1000 : 0) + frames * 10 + (evidenceSource(e) === 'measured' ? 1 : 0)
}

export function PipelinePage({ ctx }: { ctx: Ctx }) {
  const { scenario, variant } = ctx
  const viewQ = useAsync(() => (variant ? api.view(scenario, variant, 1) : Promise.reject(new Error('variant를 선택하세요 (Ctrl K)'))), [scenario, variant])
  const evidenceQ = useAsync(() => (variant ? api.evidenceList(scenario, variant) : Promise.resolve({ items: [], total: 0 })), [scenario, variant])
  const scnQ = useAsync(() => api.scenario(scenario).catch(() => null), [scenario])
  const varQ = useAsync(() => (variant ? api.variant(scenario, variant).catch(() => null) : Promise.resolve(null)), [scenario, variant])
  const [lens, setLensState] = useState<Lens>(legacyLens(ctx.params.lens))
  const setLens = (l: Lens) => { setLensState(l); ctx.navigate(undefined, { lens: l }, true) }
  useEffect(() => { if (ctx.params.lens) setLensState(legacyLens(ctx.params.lens)) }, [ctx.params.lens])
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [showSw, setShowSw] = usePref('pipeline.sw', true)
  const [elk, setElk] = useState<Layout | null>(null)
  const [layoutErr, setLayoutErr] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [slice, setSlice] = useState<Slice | null>(null)
  const [showFlows, setShowFlows] = useState(true)
  const [traceId, setTraceId] = useState<string>('')
  const [mode, setMode] = usePref<Mode>('pipeline.mode', 'split')
  const [tview, setTview] = usePref<TimingView>('pipeline.timing.view', 'trace')
  const [colorBy, setColorBy] = usePref<'group' | 'frame'>('pipeline.timing.color', 'frame')
  const [split, setSplit] = usePref<number>('pipeline.split', 50)
  const workRef = useRef<HTMLDivElement>(null)
  const splitBase = useRef(50)
  const onSplit = (d: number) => {
    const w = workRef.current?.getBoundingClientRect().width ?? 1000
    setSplit(Math.round(Math.min(78, Math.max(22, splitBase.current + (d / w) * 100))))
  }

  useEffect(() => { if (variant) rememberRecent(scenario, variant) }, [scenario, variant])
  useEffect(() => { setSelected(null); setSlice(null); setTraceId('') }, [scenario, variant])

  const view = viewQ.data
  const model = useMemo(() => (view ? buildModel(view, scnQ.data, varQ.data) : null), [view, scnQ.data, varQ.data])

  // ---- timing evidence
  const traces = useMemo(() => (evidenceQ.data?.items ?? []).filter((e) => (e.timeline_events ?? []).length > 3).sort((a, b) => rankTrace(b) - rankTrace(a)), [evidenceQ.data])
  const trace: Evidence | undefined = traces.find((t) => t.id === traceId) ?? traces[0]
  const timeline = useMemo(() => (trace ? buildTimeline(trace.timeline_events ?? [], { maxFrames: 16 }) : null), [trace])
  const timing = useMemo(() => (timeline ? stageTimings(timeline) : undefined), [timeline])
  const activePids = useMemo(() => new Set(model?.ips.map((i) => i.pid) ?? []), [model])
  const notes = useMemo(() => modeNotes(varQ.data?.design_conditions ?? null, activePids, varQ.data?.routing_switch?.disabled_nodes ?? []), [varQ.data, activePids])
  const laneOfPid = useCallback((pid: string) => model?.byPid.get(pid)?.lane ?? (pid.startsWith('sensor') ? 'sensor' : undefined), [model])
  const fps = model?.fps ?? null

  // ---- graphs
  const [paneRef, paneW] = useWidth<HTMLDivElement>(900)
  const fitW = Math.round(paneW / 40) * 40 // quantise → no relayout on every resize pixel
  const merged = useMemo(() => {
    const m = new Map<string, string>()
    Object.entries(varQ.data?.node_configs ?? {}).forEach(([sw, cfg]) => {
      const inc = ((cfg as { sw_timing?: { includes_hw_nodes?: string[] } }).sw_timing?.includes_hw_nodes) ?? []
      inc.forEach((hw) => m.set(hw, sw))
    })
    return m
  }, [varQ.data])
  const seqLayout = useMemo(() => (view && lens === 'sequence' ? sequenceLayout(view, { showSw, timing, model, scenario: scnQ.data, fitWidth: fitW, merged }) : null), [view, lens, showSw, timing, model, scnQ.data, fitW, merged])
  const graph = useMemo(() => {
    if (!view || lens !== 'dma') return null
    const hidden = new Set<string>()
    if (!showSw) { hidden.add('sw'); hidden.add('control') }
    return buildGraph(view, collapsed, hidden, model)
  }, [view, collapsed, lens, showSw, model])
  useEffect(() => {
    if (!graph) return
    let alive = true
    setLayoutErr(null)
    layoutGraph(graph, { stackColumns: showSw ? 3 : 2 }).then((l) => { if (alive) setElk(l) }).catch((e: unknown) => { if (alive) setLayoutErr(String(e)) })
    return () => { alive = false }
  }, [graph]) // eslint-disable-line react-hooks/exhaustive-deps
  const layout = lens === 'sequence' ? seqLayout : lens === 'dma' ? elk : null

  const related = useMemo(() => {
    const s = new Set<string>()
    if (!selected || !layout) return s
    s.add(selected)
    layout.edges.forEach((e) => {
      if (e.source === selected) { s.add(e.target); if (e.target.startsWith('buf:')) layout.edges.filter((x) => x.source === e.target).forEach((x) => s.add(x.target)) }
      if (e.target === selected) { s.add(e.source); if (e.source.startsWith('buf:')) layout.edges.filter((x) => x.target === e.source).forEach((x) => s.add(x.source)) }
    })
    return s
  }, [selected, layout])

  const selectedPid = selected && !selected.startsWith('buf:') ? pipelineIdOf(selected) : null
  const selectedIp: IpModel | undefined = selectedPid ? model?.byPid.get(selectedPid) : undefined
  const selectedBuf: BufferRow | undefined = selected?.startsWith('buf:') ? model?.buffers.find((b) => `buf:${b.name}` === selected) : undefined

  const selectSlice = (s: Slice | null) => {
    setSlice(s)
    if (s?.nodeId) {
      const ip = model?.byPid.get(pipelineIdOf(s.nodeId.replace(/^stage:/, '')))
      setSelected(ip ? ip.viewId : null)
    }
  }
  const selectNode = (id: string | null) => {
    setSelected(id)
    const pid = id && !id.startsWith('buf:') ? pipelineIdOf(id) : null
    const first = pid && timeline ? timeline.slices.filter((s) => s.nodeId && pipelineIdOf(s.nodeId.replace(/^stage:/, '')) === pid).sort((a, b) => a.start - b.start)[0] : undefined
    setSlice(first ?? null)
  }
  const highlightPid = selectedPid

  const flowsOf = (dir: 'in' | 'out') => (slice && timeline ? timeline.flows.filter((f) => (dir === 'in' ? f.to === slice.id : f.from === slice.id))
    .map((f) => timeline.slices.find((s) => s.id === (dir === 'in' ? f.from : f.to))).filter((s): s is Slice => !!s) : [])

  const legend = lens === 'ip' ? null : (
    <div className="legend-mini">
      <span className="legend-item"><svg width="20" height="6"><line x1="0" y1="3" x2="20" y2="3" stroke="#2563EB" strokeWidth="2" /></svg>OTF</span>
      <span className="legend-item"><svg width="20" height="6"><line x1="0" y1="3" x2="20" y2="3" stroke="#F97316" strokeWidth="2" strokeDasharray="5 3" /></svg>M2M</span>
      <span className="legend-item"><svg width="20" height="6"><line x1="0" y1="3" x2="20" y2="3" stroke="#A16207" strokeWidth="1.6" strokeDasharray="2 3" /></svg>SW trigger</span>
      <span className="legend-item"><span className="sw-ip" />IP</span>
      {lens === 'dma' && <><span className="legend-item"><span className="sw-buf" />Buffer</span>
        <span className="legend-item"><span className="sw-buf" style={{ background: '#EEF2FF', borderColor: '#4F46E5' }} />history</span>
        <span className="legend-item"><span className="sw-buf" style={{ background: '#FFF7E6', borderColor: '#B45309', borderStyle: 'dashed' }} />stat</span></>}
    </div>
  )

  // ---- tables
  const bufCols: Column<BufferRow>[] = [
    { key: 'kind', label: 'Type', width: 76, sort: (b) => b.kind, render: (b) => <span className={`badge buf-${b.kind}`}>{b.kind}</span> },
    { key: 'producer', label: 'Producer', width: 110, sort: (b) => b.producer, render: (b) => b.producer },
    { key: 'wport', label: 'WDMA port', width: 170, sort: (b) => b.wPorts.join(','), title: (b) => b.wPorts.join(', '), render: (b) => <span className="mono">{b.wPorts.join(', ') || '—'}</span> },
    { key: 'buffer', label: 'Buffer', width: 150, sort: (b) => b.name, render: (b) => <span className="mono">{b.name}</span> },
    { key: 'rport', label: 'RDMA port', width: 190, sort: (b) => b.rPorts.join(','), title: (b) => b.rPorts.join(', '), render: (b) => <span className="mono">{b.rPorts.join(', ') || '—'}</span> },
    { key: 'consumer', label: 'Consumer', width: 110, sort: (b) => b.consumers.join(','), render: (b) => b.consumers.join(', ') || '—' },
    { key: 'size', label: 'W×H', width: 96, sort: (b) => (b.width && b.height ? b.width * b.height : null), render: (b) => <span className="mono">{b.width ? `${b.width}×${b.height}` : '—'}</span> },
    { key: 'fmt', label: 'Format', width: 80, sort: (b) => b.format || null, render: (b) => b.format || '—' },
    { key: 'bit', label: 'Bit', width: 48, sort: (b) => Number(b.bit) || null, render: (b) => b.bit || '—' },
    { key: 'comp', label: 'Comp', width: 88, sort: (b) => b.comp || null, render: (b) => b.comp || '—' },
    { key: 'mb', label: 'MB/f', width: 66, align: 'right', sort: (b) => b.mbFrame, render: (b) => <span className="mono">{b.mbFrame ?? '—'}</span> },
    { key: 'w', label: 'W MB/s', width: 74, align: 'right', sort: (b) => b.wMBs, render: (b) => <span className="mono">{b.wMBs ?? '—'}</span> },
    { key: 'r', label: 'R MB/s', width: 74, align: 'right', sort: (b) => b.rMBs, render: (b) => <span className="mono">{b.rMBs ?? '—'}</span> },
    { key: 'note', label: 'Note', width: 280, title: (b) => b.note, render: (b) => <span className="faint">{b.enabled ? '' : '[off] '}{b.note}</span> },
  ]
  const ipCols: Column<IpModel>[] = [
    { key: 'lane', label: 'Lane', width: 90, sort: (i) => i.lane, render: (i) => LANE_LABEL[i.lane] },
    { key: 'ip', label: 'IP / SW', width: 120, sort: (i) => i.label, render: (i) => <b>{i.label}</b> },
    { key: 'in', label: 'In (처리)', width: 100, sort: (i) => i.inSize || null, render: (i) => <span className="mono">{i.inSize || '—'}</span> },
    { key: 'out', label: 'Out (WDMA)', width: 170, sort: (i) => i.outSizes.join(',') || null, render: (i) => <span className="mono">{i.outSizes.join(' / ') || '—'}</span> },
    { key: 'ops', label: 'Ops', width: 150, sort: (i) => i.ops.join(',') || null, render: (i) => i.ops.join(' · ') || '—' },
    { key: 'mode', label: 'Mode', width: 110, sort: (i) => i.mode ?? null, title: (i) => i.mode, render: (i) => i.mode ?? '—' },
    { key: 'rd', label: 'RDMA', width: 58, align: 'right', sort: (i) => i.ports.filter((p) => p.dir === 'in' && p.via !== 'OTF' && p.via !== 'ctrl').length, render: (i) => i.ports.filter((p) => p.dir === 'in' && p.via !== 'OTF' && p.via !== 'ctrl').length },
    { key: 'wr', label: 'WDMA', width: 58, align: 'right', sort: (i) => i.ports.filter((p) => p.dir === 'out' && p.via !== 'OTF' && p.via !== 'ctrl').length, render: (i) => i.ports.filter((p) => p.dir === 'out' && p.via !== 'OTF' && p.via !== 'ctrl').length },
    { key: 'start', label: '+start ms', width: 80, align: 'right', sort: (i) => timing?.get(i.pid)?.offset ?? null, render: (i) => <span className="mono">{timing?.get(i.pid)?.offset.toFixed(2) ?? '—'}</span> },
    { key: 'dur', label: 'dur ms', width: 70, align: 'right', sort: (i) => timing?.get(i.pid)?.dur ?? i.sw?.mean ?? null, render: (i) => <span className="mono">{timing?.get(i.pid)?.dur.toFixed(2) ?? (i.sw?.mean !== undefined ? `${i.sw.mean}*` : '—')}</span> },
    { key: 'flags', label: 'Config', width: 260, title: (i) => i.flags.map(([k, v]) => `${k}=${v}`).join(' · '), render: (i) => <span className="faint">{i.flags.map(([k, v]) => `${k}=${v}`).join(' · ')}</span> },
  ]
  const onIpRow = (i: IpModel) => selectNode(i.viewId)
  const st: StageTiming | undefined = selectedPid ? timing?.get(selectedPid) : undefined

  return (
    <PageLayout id="pipeline"
      top={<>
      <div className="toolbar">
        <div className="seg" role="group" aria-label="화면 구성">
          {([['split', '나란히'], ['graph', 'Pipeline'], ['timing', 'Timing']] as [Mode, string][]).map(([k, l]) =>
            <button key={k} className={mode === k ? 'on' : ''} onClick={() => setMode(k)}>{l}</button>)}
        </div>
        <div className="seg" role="group" aria-label="보기 관점">
          {LENS.map((l) => <button key={l.id} className={lens === l.id ? 'on' : ''} onClick={() => setLens(l.id)} title={l.hint}>{l.label}</button>)}
        </div>
        {lens !== 'ip' && <label className="muted" style={{ fontSize: 13, display: 'flex', gap: 6, alignItems: 'center' }}><input type="checkbox" checked={showSw} onChange={(e) => setShowSw(e.target.checked)} />SW task</label>}
        {notes.map((n) => <span key={n.id} className={`chip mode-${n.tone}`} title={n.detail}>{n.label}</span>)}
        <span className="grow" />
        {view && <><span className="chip">{view.summary.subtitle}</span><span className="chip">period {view.summary.period_ms} ms</span>
          {model && <span className="chip" title={`특성화된 buffer W+R 합계 · size 미정 ${model.unknownBuffers}개 제외`}>DMA {model.totalMBs.toFixed(0)} MB/s</span>}</>}
        <button className="btn" onClick={() => ctx.navigate('compare', { scenario, variants: variant })}>Compare에 추가</button>
      </div>
      <div className="lens-hint"><b>{LENS.find((l) => l.id === lens)?.label}</b> {LENS.find((l) => l.id === lens)?.hint}</div>
      {graph && lens === 'dma' && mode !== 'timing' && <div className="facet-row">
        <span className="faint" style={{ fontSize: 12, marginRight: 4 }}>그룹 접기</span>
        {graph.groups.map((g) => (
          <button key={g.id} className={`grp-chip ${collapsed.has(g.id) ? 'off' : ''}`} onClick={() => setCollapsed((c) => { const s = new Set(c); if (s.has(g.id)) s.delete(g.id); else s.add(g.id); return s })}>{g.label} · {g.count}</button>
        ))}
      </div>}
      </>}
      main={
      <div className="workspace" ref={workRef}>
        {mode !== 'timing' && <section className="panel pane" style={{ flex: mode === 'split' ? `0 0 ${split}%` : '1 1 auto' }}>
          <div className="pane-head"><h2>{lens === 'ip' ? 'IP 내부' : lens === 'dma' ? 'DMA · Memory' : 'Sequence'}</h2>
            {lens === 'sequence' && trace && <span className="faint" style={{ fontSize: 11, whiteSpace: 'nowrap' }}>timing: {evidenceSource(trace)}</span>}{legend}</div>
          <div className="pane-body" ref={paneRef}>
            {viewQ.error && <div className="err" style={{ margin: 12 }}>{viewQ.error}</div>}
            {lens === 'dma' && layoutErr && <div className="err" style={{ margin: 12 }}>Layout 실패: {layoutErr}</div>}
            {lens !== 'ip' && (viewQ.loading || (!layout && !layoutErr && !viewQ.error)) && <div className="empty">Layout 계산 중…</div>}
            {lens !== 'ip' && layout && !viewQ.error && <GraphView layout={layout} selected={selected} related={related} onSelect={selectNode} showOps={false}
              onToggleGroup={(g) => setCollapsed((c) => { const s = new Set(c); if (s.has(g)) s.delete(g); else s.add(g); return s })} />}
            {lens === 'ip' && model && <IpInternalView model={model} selectedPid={selectedPid} onSelect={selectNode} />}
          </div>
        </section>}
        {mode === 'split' && <Resizer axis="x" label="Pipeline | Timing 폭" onStart={() => { splitBase.current = split }} onResize={onSplit} onReset={() => setSplit(50)} />}
        {mode !== 'graph' && <section className="panel pane" style={{ flex: '1 1 0' }}>
          <div className="pane-head">
            <h2>Timing</h2>
            <div className="seg sm" role="group" aria-label="Timing 보기">
              <button className={tview === 'trace' ? 'on' : ''} onClick={() => setTview('trace')}>Trace</button>
              <button className={tview === 'cadence' ? 'on' : ''} onClick={() => setTview('cadence')}>주기 · 지연</button>
            </div>
            {trace && <span className={`badge src-${evidenceSource(trace)}`}>{evidenceSource(trace)}</span>}
            {traces.length > 0 && <select value={trace?.id ?? ''} onChange={(e) => { setTraceId(e.target.value); setSlice(null) }} aria-label="timing evidence" style={{ minWidth: 0, flex: '0 1 300px' }}>
              {traces.map((t) => <option key={t.id} value={t.id}>{evidenceSource(t)} · {new Set((t.timeline_events ?? []).map((x) => x.frame_index)).size}f · {t.id}</option>)}
            </select>}
            <span className="grow" />
            {tview === 'trace' && <>
              <select value={colorBy} onChange={(e) => setColorBy(e.target.value as 'group' | 'frame')} aria-label="색 기준" title="frame 색 = RT(N+1)과 NRT(N) 중첩이 보임">
                <option value="frame">색: frame</option><option value="group">색: stage</option></select>
              <label className="muted" style={{ fontSize: 12, display: 'flex', gap: 5, whiteSpace: 'nowrap' }}><input type="checkbox" checked={showFlows} onChange={(e) => setShowFlows(e.target.checked)} />Flow</label></>}
          </div>
          <div className="pane-body">
            {evidenceQ.loading && <div className="empty">Evidence 불러오는 중…</div>}
            {!evidenceQ.loading && !timeline && <div className="empty">이 variant에는 timeline event가 있는 evidence가 없습니다. Camera Profiling에서 trace를 import하거나 simulation을 저장하세요.</div>}
            {timeline && tview === 'trace' && <TimelineView timeline={timeline} selectedSlice={slice?.id ?? null} colorBy={colorBy}
              highlightNode={slice ? null : highlightPid} showFlows={showFlows} onSelect={selectSlice} />}
            {timeline && tview === 'cadence' && <CadenceView timeline={timeline} view={view} fps={fps} laneOfPid={laneOfPid} notes={notes} source={trace ? `${evidenceSource(trace)} · ${trace.id}` : ''} />}
          </div>
        </section>}
      </div>
      }
      bottomTabs={[
        { id: 'sel', label: <>선택 상세{selectedIp ? <span className="tab-note"> · {selectedIp.label}</span> : selectedBuf ? <span className="tab-note"> · {selectedBuf.name}</span> : slice ? <span className="tab-note"> · {slice.label}</span> : null}</>, content: (
        <div className="sel-grid">
          <div>
            <h5>Timing slice</h5>
            {slice ? <>
              <div className="kv"><span>Name</span><span className="mono">{slice.label}{slice.frame !== null ? ` · f${slice.frame}` : ''}</span></div>
              <div className="kv"><span>Track</span><span>{slice.group} › {timeline?.groups.flatMap((g) => g.tracks).find((t) => t.id === slice.track)?.name}</span></div>
              <div className="kv"><span>Start / Duration</span><span className="mono">{slice.start.toFixed(3)} / {(slice.end - slice.start).toFixed(3)} ms</span></div>
              {st && <div className="kv"><span>frame 기준 평균</span><span className="mono">+{st.offset.toFixed(2)} · {st.dur.toFixed(2)} ms ({st.durMin.toFixed(2)}–{st.durMax.toFixed(2)}, n{st.n})</span></div>}
              <h5 style={{ marginTop: 10 }}>Flows</h5>
              <div style={{ fontSize: 13, lineHeight: 1.8 }}>
                {flowsOf('in').map((s) => <div key={`i${s.id}`}><span className="faint">Preceding</span> · <a href="#" onClick={(e) => { e.preventDefault(); selectSlice(s) }}>{s.label} f{s.frame}</a></div>)}
                {flowsOf('out').map((s) => <div key={`o${s.id}`}><span className="faint">Following</span> · <a href="#" onClick={(e) => { e.preventDefault(); selectSlice(s) }}>{s.label} f{s.frame}</a></div>)}
                {!flowsOf('in').length && !flowsOf('out').length && <span className="faint">연결된 flow 없음</span>}
              </div>
            </> : <div className="faint" style={{ fontSize: 13 }}>timing slice 또는 그래프 노드를 선택하세요.</div>}
          </div>
          <div>
            <h5>{selectedBuf ? `Buffer · ${selectedBuf.name}` : `IP ${selectedIp ? `· ${selectedIp.label}` : ''}`}</h5>
            {selectedBuf ? <>
              <div className="kv"><span>Type</span><span>{selectedBuf.kind}{selectedBuf.enabled ? '' : ' · off'}</span></div>
              <div className="kv"><span>Producer → Consumer</span><span>{selectedBuf.producer} → {selectedBuf.consumers.join(', ') || '—'}</span></div>
              <div className="kv"><span>WDMA</span><span className="mono">{selectedBuf.wPorts.join(', ') || '—'}</span></div>
              <div className="kv"><span>RDMA</span><span className="mono">{selectedBuf.rPorts.join(', ') || '—'}</span></div>
              <div className="kv"><span>Size / fmt</span><span className="mono">{memoryText({ width: selectedBuf.width, height: selectedBuf.height, format: selectedBuf.format, bitdepth: selectedBuf.bit, compression: selectedBuf.comp }) || '미정'}</span></div>
              <div className="kv"><span>MB/f · W / R MB/s</span><span className="mono">{selectedBuf.mbFrame ?? '—'} · {selectedBuf.wMBs ?? '—'} / {selectedBuf.rMBs ?? '—'}</span></div>
              {selectedBuf.note && <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>{selectedBuf.note}</div>}
            </> : selectedIp ? <>
              <div className="kv"><span>Lane</span><span>{LANE_LABEL[selectedIp.lane]}</span></div>
              <div className="kv"><span>In → Out</span><span className="mono">{selectedIp.inSize || '—'} → {selectedIp.outSizes.join(' / ') || '—'}</span></div>
              {selectedIp.ops.length > 0 && <div className="kv"><span>Ops</span><span>{selectedIp.ops.join(' · ')}</span></div>}
              {selectedIp.mode && <div className="kv"><span>Mode</span><span className="mono">{selectedIp.mode}</span></div>}
              {selectedIp.sw && <div className="kv"><span>SW time (정의)</span><span className="mono">{selectedIp.sw.mean} ms ({selectedIp.sw.min}–{selectedIp.sw.max}) · {selectedIp.sw.source}</span></div>}
              {selectedIp.flags.map(([k, v]) => <div key={k} className="kv"><span>{k}</span><span className="mono">{v}</span></div>)}
              <a href="#" style={{ fontSize: 12 }} onClick={(e) => { e.preventDefault(); setLens('ip'); if (mode === 'timing') setMode('split') }}>IP 내부 보기 →</a>
            </> : <span className="faint" style={{ fontSize: 13 }}>그래프 노드, timing slice, 표 행 중 하나를 선택하면 서로 연동됩니다.</span>}
          </div>
          <div style={{ borderRight: 0 }}>
            <h5>Ports {selectedIp ? `· ${selectedIp.ports.length}` : ''}</h5>
            {selectedIp ? selectedIp.ports.map((p, i) => (
              <div key={i} className="kv"><span>{p.dir === 'in' ? '←' : '→'} <span className="mono">{p.port}</span> <span className="faint">({p.via}{p.buffer ? ` · ${p.buffer}` : ''})</span></span>
                <span className="mono">{[p.size, p.format, p.bit ? `${p.bit}b` : ''].filter(Boolean).join(' ') || p.peer || ''}</span></div>
            )) : <span className="faint" style={{ fontSize: 13 }}>—</span>}
          </div>
        </div>
        ) },
        { id: 'dma', label: <>DMA · Buffer <span className="tab-note">{model?.buffers.length ?? 0} · {model?.totalMBs.toFixed(0) ?? 0} MB/s</span></>, content: (
        <div className="table-scroll" style={{ height: '100%' }}>
          {model && <DataTable id="pipeline.dma" columns={bufCols} rows={model.buffers} rowKey={(b) => b.name}
            rowClass={(b) => `${selected === `buf:${b.name}` ? 'sel' : ''} ${b.enabled ? '' : 'row-off'}`} onRowClick={(b) => selectNode(`buf:${b.name}`)} />}
        </div>
        ) },
        { id: 'ips', label: <>IP In/Out · Timing <span className="tab-note">{model?.ips.length ?? 0}</span></>, content: (
        <div className="table-scroll" style={{ height: '100%' }}>
          {model && <DataTable id="pipeline.ips" columns={ipCols} rows={model.ips} rowKey={(i) => i.pid} onRowClick={onIpRow}
            rowClass={(i) => (i.pid === selectedPid ? 'sel' : '')} />}
          <div className="faint" style={{ fontSize: 11, padding: '6px 12px' }}>+start = frame의 sensor readout 시작 기준 평균 · * = trace 없음, 정의된 SW time(assumed)</div>
        </div>
        ) },
      ]} />
  )
}
