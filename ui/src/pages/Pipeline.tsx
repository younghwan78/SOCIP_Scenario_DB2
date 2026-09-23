import { useEffect, useMemo, useRef, useState } from 'react'
import type { Ctx } from '../App'
import { api, type Evidence } from '../lib/api'
import { useAsync } from '../lib/route'
import { buildGraph, dmaRows, layoutGraph, memoryText, pipelineIdOf, type Layout } from '../lib/graph'
import { buildTimeline, type Slice } from '../lib/timeline'
import { evidenceSource } from '../lib/conditions'
import { GraphView } from '../components/GraphView'
import { TimelineView } from '../components/TimelineView'
import { rememberRecent } from '../components/Picker'

type Lens = 'topology' | 'dma' | 'transform'

function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null)
  const [w, setW] = useState(1100)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

export function PipelinePage({ ctx }: { ctx: Ctx }) {
  const { scenario, variant } = ctx
  const viewQ = useAsync(() => (variant ? api.view(scenario, variant, 1) : Promise.reject(new Error('variant를 선택하세요 (Ctrl K)'))), [scenario, variant])
  const evidenceQ = useAsync(() => (variant ? api.evidenceList(scenario, variant) : Promise.resolve({ items: [], total: 0 })), [scenario, variant])
  const [lens, setLens] = useState<Lens>((ctx.params.lens as Lens) ?? 'dma')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [showSw, setShowSw] = useState(true)
  const [layout, setLayout] = useState<Layout | null>(null)
  const [layoutErr, setLayoutErr] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [slice, setSlice] = useState<Slice | null>(null)
  const [zoom, setZoom] = useState(1)
  const [showFlows, setShowFlows] = useState(true)
  const [traceId, setTraceId] = useState<string>('')
  const [timingRef, timingW] = useWidth<HTMLDivElement>()
  const [graphRef, graphW] = useWidth<HTMLDivElement>()
  const [autoFit, setAutoFit] = useState(true)

  useEffect(() => { if (variant) rememberRecent(scenario, variant) }, [scenario, variant])
  useEffect(() => { setSelected(null); setSlice(null) }, [scenario, variant])

  const graph = useMemo(() => {
    if (!viewQ.data) return null
    const hidden = new Set<string>()
    if (lens !== 'dma') hidden.add('buffer')
    if (!showSw) { hidden.add('sw'); hidden.add('control') }
    return buildGraph(viewQ.data, collapsed, hidden)
  }, [viewQ.data, collapsed, lens, showSw])

  useEffect(() => {
    if (!graph) return
    let alive = true
    setLayoutErr(null)
    layoutGraph(graph).then((l) => { if (alive) setLayout(l) }).catch((e: unknown) => { if (alive) setLayoutErr(String(e)) })
    return () => { alive = false }
  }, [graph])

  useEffect(() => {
    // Fit the layout width to the panel, but never shrink labels below ~70%.
    if (layout && autoFit) setZoom(Math.min(1, Math.max(0.75, (graphW - 20) / layout.width)))
  }, [layout, graphW, autoFit])
  useEffect(() => {
    // Wide layouts overflow horizontally: start the viewport on the sensor (pipeline source).
    const el = graphRef.current
    const src = layout?.nodes.find((n) => n.kind === 'external')
    if (!el || !layout || !src) return
    el.scrollLeft = Math.max(0, (src.x + src.width / 2) * zoom - el.clientWidth / 2)
  }, [layout]) // eslint-disable-line react-hooks/exhaustive-deps

  const related = useMemo(() => {
    const s = new Set<string>()
    if (!selected || !graph) return s
    s.add(selected)
    graph.edges.forEach((e) => {
      if (e.source === selected) { s.add(e.target); if (e.target.startsWith('buf:')) graph.edges.filter((x) => x.source === e.target).forEach((x) => s.add(x.target)) }
      if (e.target === selected) { s.add(e.source); if (e.source.startsWith('buf:')) graph.edges.filter((x) => x.target === e.source).forEach((x) => s.add(x.source)) }
    })
    return s
  }, [selected, graph])

  const traces = (evidenceQ.data?.items ?? []).filter((e) => (e.timeline_events ?? []).length > 3)
  const trace: Evidence | undefined = traces.find((t) => t.id === traceId) ?? traces.find((t) => evidenceSource(t) !== 'calculated') ?? traces[0]
  const timeline = useMemo(() => (trace ? buildTimeline(trace.timeline_events ?? [], { maxFrames: 4 }) : null), [trace])
  const selectedNode = graph?.nodes.find((n) => n.id === selected)
  const highlightPid = selectedNode?.pipelineId ?? null

  const selectSlice = (s: Slice | null) => {
    setSlice(s)
    if (s?.nodeId && graph) {
      const n = graph.nodes.find((g) => g.pipelineId === s.nodeId)
      setSelected(n ? n.id : null)
    }
  }
  const selectNode = (id: string | null) => {
    setSelected(id)
    const pid = id ? pipelineIdOf(id) : null
    const first = pid && timeline ? timeline.slices.filter((s) => s.nodeId === pid).sort((a, b) => a.start - b.start)[0] : undefined
    setSlice(first ?? null)
  }

  const view = viewQ.data
  const dma = view ? dmaRows(view) : []
  const nodeEdges = view && selectedNode?.data ? view.edges.map((e) => e.data).filter((e) => e.source === selectedNode.data!.id || e.target === selectedNode.data!.id) : []
  const label = (id: string) => view?.nodes.find((n) => n.data.id === id)?.data.label ?? id
  const flowsOf = (dir: 'in' | 'out') => (slice && timeline ? timeline.flows.filter((f) => (dir === 'in' ? f.to === slice.id : f.from === slice.id))
    .map((f) => timeline.slices.find((s) => s.id === (dir === 'in' ? f.from : f.to))).filter((s): s is Slice => !!s) : [])
  const ids = new Set((view?.nodes ?? []).map((n) => pipelineIdOf(n.data.id)))
  const tracksText = timeline ? timeline.groups.flatMap((g) => g.tracks.map((t) => t.name.toUpperCase())).join(' ') : ''
  const concurrent = [
    { name: 'VPS · DOF / SEG', state: ids.has('vps_dof') || ids.has('vps_seg') ? '동작' : 'disabled', note: ids.has('vps_od') ? 'VPS OD는 동작' : '' },
    { name: 'Audio · ABOX', state: [...ids].some((i) => i.includes('abox')) ? '동작' : '모델 추가 예정', note: 'mic → AAC enc' },
    { name: 'iCPU · camera FW', state: /ICPU/.test(tracksText) ? 'trace 있음' : 'task 추가 예정', note: '3A · ISP 제어' },
  ]

  return (
    <div className="page">
      <div className="toolbar">
        <div className="seg" role="group" aria-label="보기 관점">
          {([['topology', 'Topology'], ['dma', 'DMA · Memory'], ['transform', 'Transform']] as [Lens, string][]).map(([k, l]) =>
            <button key={k} className={lens === k ? 'on' : ''} onClick={() => setLens(k)}>{l}</button>)}
        </div>
        <label className="muted" style={{ fontSize: 13, display: 'flex', gap: 6, alignItems: 'center' }}><input type="checkbox" checked={showSw} onChange={(e) => setShowSw(e.target.checked)} />SW task</label>
        <span className="grow" />
        {view && <><span className="chip">{view.summary.subtitle}</span><span className="chip">period {view.summary.period_ms} ms</span><span className="chip">budget {view.summary.budget_ms} ms</span></>}
        <button className="btn" onClick={() => ctx.navigate('compare', { scenario, variants: variant })}>Compare에 추가</button>
      </div>
      {graph && <div className="facet-row">
        <span className="faint" style={{ fontSize: 12, marginRight: 4 }}>그룹 (클릭 = 접기/펼치기)</span>
        {graph.groups.map((g) => (
          <button key={g.id} className={`grp-chip ${collapsed.has(g.id) ? 'off' : ''}`} onClick={() => setCollapsed((c) => { const s = new Set(c); if (s.has(g.id)) s.delete(g.id); else s.add(g.id); return s })}>{g.label} · {g.count}</button>
        ))}
      </div>}

      <section className="panel">
        <div className="graph-legend">
          <span className="legend-item"><svg width="26" height="6"><line x1="0" y1="3" x2="26" y2="3" stroke="#2563EB" strokeWidth="2" /></svg>OTF</span>
          <span className="legend-item"><svg width="26" height="6"><line x1="0" y1="3" x2="26" y2="3" stroke="#F97316" strokeWidth="2" strokeDasharray="5 3" /></svg>M2M (WDMA→RDMA)</span>
          <span className="legend-item"><svg width="26" height="6"><line x1="0" y1="3" x2="26" y2="3" stroke="#A16207" strokeWidth="1.6" strokeDasharray="2 3" /></svg>SW control</span>
          <span className="legend-item"><span style={{ width: 14, height: 10, background: 'var(--ip-fill)', border: '1px solid var(--ip-line)', borderRadius: 3 }} />SoC IP</span>
          <span className="legend-item"><span style={{ width: 14, height: 10, background: 'var(--buf-fill)', border: '1px solid var(--buf-line)', borderRadius: 3 }} />Buffer</span>
          <span className="legend-item"><span style={{ width: 14, height: 10, background: 'var(--ext-fill)', border: '1.5px solid var(--ext-line)', borderRadius: 6 }} />External module</span>
          <span className="grow" />
          <button className="btn" onClick={() => { setAutoFit(false); setZoom((z) => Math.max(0.4, z - 0.1)) }} aria-label="축소">－</button>
          <span className="mono" style={{ fontSize: 12 }}>{Math.round(zoom * 100)}%</span>
          <button className="btn" onClick={() => { setAutoFit(false); setZoom((z) => Math.min(2, z + 0.1)) }} aria-label="확대">＋</button>
          <button className="btn" onClick={() => setAutoFit(true)}>Fit</button>
        </div>
        <div className="graph-row">
        <div className="graph-wrap" ref={graphRef} style={{ maxHeight: 820 }}>
          {viewQ.error && <div className="err" style={{ margin: 12 }}>{viewQ.error}</div>}
          {layoutErr && <div className="err" style={{ margin: 12 }}>Layout 실패: {layoutErr}</div>}
          {(viewQ.loading || (!layout && !layoutErr && !viewQ.error)) && <div className="empty">Layout 계산 중…</div>}
          {layout && !viewQ.error && <GraphView layout={layout} selected={selected} related={related} onSelect={selectNode} zoom={zoom} showOps={lens === 'transform'}
            onToggleGroup={(g) => setCollapsed((c) => { const s = new Set(c); if (s.has(g)) s.delete(g); else s.add(g); return s })} />}
        </div>
          <aside className="concurrent" aria-label="동시 동작 subsystem">
            <h4>동시 동작 subsystem</h4>
            {concurrent.map((c) => (
              <div key={c.name} className={`cc-item ${c.state === 'disabled' ? 'off' : ''}`}>
                <span><b style={{ fontWeight: 600 }}>{c.name}</b><br /><span className="faint">{c.note}</span></span>
                <span style={{ color: c.state === '동작' || c.state === 'trace 있음' ? 'var(--primary)' : '#B45309', whiteSpace: 'nowrap' }}>{c.state}</span>
              </div>
            ))}
          </aside>
        </div>
      </section>

      <section className="panel" ref={timingRef}>
        <div className="panel-head">
          <h2>Timing</h2>
          {trace && <span className={`badge src-${evidenceSource(trace)}`}>{evidenceSource(trace)}</span>}
          {traces.length > 0 && <select value={trace?.id ?? ''} onChange={(e) => { setTraceId(e.target.value); setSlice(null) }} aria-label="timing evidence">
            {traces.map((t) => <option key={t.id} value={t.id}>{evidenceSource(t)} · {t.id}</option>)}
          </select>}
          <span className="grow" />
          <label className="muted" style={{ fontSize: 12, display: 'flex', gap: 5 }}><input type="checkbox" checked={showFlows} onChange={(e) => setShowFlows(e.target.checked)} />Flow arrows</label>
        </div>
        {evidenceQ.loading && <div className="empty">Evidence 불러오는 중…</div>}
        {!evidenceQ.loading && !timeline && <div className="empty">이 variant에는 timeline event가 있는 evidence가 없습니다. Camera Profiling에서 trace를 import하거나 simulation을 저장하세요.</div>}
        {timeline && <div className="timeline-wrap"><TimelineView timeline={timeline} width={Math.max(timingW - 2, 700)} selectedSlice={slice?.id ?? null}
          highlightNode={slice ? null : highlightPid} showFlows={showFlows} onSelect={selectSlice} /></div>}
        <div className="sel-grid">
          <div>
            <h5>Current selection · Slice</h5>
            {slice ? <>
              <div className="kv"><span>Name</span><span className="mono">{slice.label}{slice.frame !== null ? ` · f${slice.frame}` : ''}</span></div>
              <div className="kv"><span>Track</span><span>{slice.group} › {timeline?.groups.flatMap((g) => g.tracks).find((t) => t.id === slice.track)?.name}</span></div>
              <div className="kv"><span>Start / Duration</span><span className="mono">{slice.start.toFixed(3)} / {(slice.end - slice.start).toFixed(3)} ms</span></div>
            </> : <div className="faint" style={{ fontSize: 13 }}>timing slice 또는 그래프 노드를 선택하세요.</div>}
          </div>
          <div>
            <h5>Flows</h5>
            {slice ? <div style={{ fontSize: 13, lineHeight: 1.8 }}>
              {flowsOf('in').map((s) => <div key={`i${s.id}`}><span className="faint">Preceding</span> · <a href="#" onClick={(e) => { e.preventDefault(); selectSlice(s) }}>{s.label} f{s.frame}</a></div>)}
              {flowsOf('out').map((s) => <div key={`o${s.id}`}><span className="faint">Following</span> · <a href="#" onClick={(e) => { e.preventDefault(); selectSlice(s) }}>{s.label} f{s.frame}</a></div>)}
              {!flowsOf('in').length && !flowsOf('out').length && <span className="faint">연결된 flow 없음</span>}
            </div> : <span className="faint" style={{ fontSize: 13 }}>—</span>}
          </div>
          <div style={{ borderRight: 0 }}>
            <h5>Node {selectedNode ? `· ${selectedNode.label}` : ''}</h5>
            {selectedNode ? <>
              {selectedNode.kind === 'buffer' ? <div className="kv"><span>{selectedNode.bufferRef}</span><span className="mono">{memoryText(selectedNode.memory)}</span></div> : <>
                <div className="facet-row" style={{ marginBottom: 6 }}>
                  {Object.entries(selectedNode.data?.active_operations ?? {}).filter(([, v]) => v === true || (typeof v === 'number' && v !== 0)).map(([k, v]) => <span key={k} className="op">{k}{typeof v === 'number' ? ` ${v}` : ''}</span>)}
                  {(selectedNode.data?.capability_badges ?? []).map((c) => <span key={c} className="op off">{c}</span>)}
                  <span className="mono faint" style={{ fontSize: 11 }}>{selectedNode.data?.ip_ref}</span>
                </div>
                {nodeEdges.map((e) => (
                  <div key={e.id} className="kv"><span>{e.source === selectedNode.data!.id ? `→ ${label(e.target)}` : `← ${label(e.source)}`} <span className="faint">({e.flow_type}{e.buffer_ref ? ` · ${e.buffer_ref}` : ''})</span></span>
                    <span className="mono">{memoryText(e.memory)}</span></div>
                ))}
              </>}
            </> : <span className="faint" style={{ fontSize: 13 }}>그래프 노드, timing slice, DMA 표 행 중 하나를 선택하면 서로 연동됩니다.</span>}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><h2>DMA · Buffer</h2><span className="muted" style={{ fontSize: 12 }}>{dma.length} transfers · 행 클릭 = 그래프 강조 · MB는 압축 전 1 frame 추정</span></div>
        <div className="table-scroll" style={{ maxHeight: 340 }}>
          <table className="grid">
            <thead><tr><th>Producer</th><th>Buffer</th><th>Consumer</th><th>Ports (WDMA → RDMA)</th><th>Size</th><th>Format</th><th>Bit</th><th>Compression</th><th style={{ textAlign: 'right' }}>MB/frame</th></tr></thead>
            <tbody>
              {dma.map((r, i) => {
                const bid = `buf:${r.buffer}`
                return (
                  <tr key={i} className={`clickable ${selected === bid ? 'sel' : ''}`} onClick={() => selectNode(graph?.nodes.some((n) => n.id === bid) ? bid : null)}>
                    <td>{r.producer}</td><td className="mono">{r.buffer}</td><td>{r.consumer}</td><td className="mono" style={{ fontSize: 11.5 }}>{r.ports || '—'}</td>
                    <td className="mono">{r.size || '—'}</td><td>{r.format}</td><td>{r.bit}</td><td>{r.compression}</td><td className="mono" style={{ textAlign: 'right' }}>{r.mb ?? '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
