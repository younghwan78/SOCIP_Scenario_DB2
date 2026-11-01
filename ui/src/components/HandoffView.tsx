// Processing flow: units (frame · buffer · period) crossing the software / hardware layers, drawn as the
// numbered sequence diagram of the original hand-off mockup. Data: sdb.handoff/1 (lib/handoff.ts).
// "All loops" stacks every unit in its own loop frame so it is visible what repeats with the frame and
// what runs independently (audio, UI, chunk write …) and where those loops hand work to each other.
import { useMemo, type ReactNode } from 'react'
import type { HandoffDoc, HandoffStep } from '../lib/api'
import { cadenceLinks, cadenceLabel, cadencePeriod, fmtHz, layerColor, layoutFlows, loopKind, LAYERS, LAYER_LABEL, stepName, type ColumnSpec, type FlowLayout, type Frame } from '../lib/handoff'
import { HANDOFF } from './TimelineView'

export const ALL_LOOPS = 'all'

interface Props {
  doc: HandoffDoc
  /** a flow id, or ALL_LOOPS (default) */
  flowId: string | null
  onFlow: (id: string) => void
  /** columns: every layer folded, every layer per process, or the listed layers per process */
  columns: ColumnSpec
  onColumns: (c: ColumnSpec) => void
  source: string
  /** a step whose slice exists in the full-stack trace can be opened there */
  canOpen?: (slice: string) => boolean
  onOpen?: (slice: string) => void
}

const DASHED = new Set(['complete', 'irq'])
const FRAME_TONE: Record<string, { stroke: string; tab: string; dash?: string }> = {
  frame: { stroke: '#2F6F68', tab: '#E3EEEB' }, vsync: { stroke: '#2F6F68', tab: '#E3EEEB' }, divided: { stroke: '#2F6F68', tab: '#E3EEEB', dash: '6 3' },
  period: { stroke: '#B7791F', tab: '#F6E3BF', dash: '6 3' }, chunk: { stroke: '#8A6D3B', tab: '#EFE5D2', dash: '6 3' }, event: { stroke: '#6B6558', tab: '#ECE8E1', dash: '2 3' },
}

export function HandoffView({ doc, flowId, onFlow, columns, onColumns, source, canOpen, onOpen }: Props) {
  const flow = doc.flows.find((f) => f.id === flowId)
  const all = !flow && doc.flows.length > 1
  const shown = all ? doc.flows : [flow ?? doc.flows[0]]
  const lay = useMemo(() => layoutFlows(doc, shown, columns), [doc, shown, columns])
  // Layer / Process: fold or spread every layer; a layer band in the header toggles that layer alone
  const multi = lay.layers.filter((l) => l.parts > 1)
  const allFolded = columns === 'layer' || (columns !== 'participant' && multi.every((l) => !l.expanded))
  const allSpread = columns === 'participant' || (columns !== 'layer' && multi.length > 0 && multi.every((l) => l.expanded))
  const toggleLayer = (layer: string) => {
    const open = new Set<string>(columns === 'participant' ? [...LAYERS, ...lay.layers.map((l) => l.layer)] : columns === 'layer' ? [] : columns)
    if (open.has(layer)) open.delete(layer); else open.add(layer)
    onColumns(open.size ? [...open] : 'layer')
  }
  const active = all ? null : shown[0].cadence
  return (
    <div className="handoff">
      <div className="handoff-bar">
        <div className="seg sm" role="tablist" aria-label="Processing unit">
          {doc.flows.length > 1 && <button role="tab" aria-selected={all} className={all ? 'on' : ''} onClick={() => onFlow(ALL_LOOPS)}
            title="모든 처리 단위를 각자의 loop로 묶어 한 화면에 표시">All loops</button>}
          {doc.flows.map((f) => (
            <button key={f.id} role="tab" aria-selected={!all && f.id === shown[0].id} className={!all && f.id === shown[0].id ? 'on' : ''} onClick={() => onFlow(f.id)} title={f.summary}>
              {f.name} <span className="faint mono">{fmtHz(cadencePeriod(doc, f.cadence))}</span>
            </button>))}
        </div>
        <div className="seg sm" role="group" aria-label="Columns">
          <button className={allFolded ? 'on' : ''} onClick={() => onColumns('layer')} title="App · Framework · HAL · Kernel · FW · HW 6열 (머리글의 layer 띠를 누르면 그 layer만 process로 펼침)">Layer</button>
          <button className={allSpread ? 'on' : ''} onClick={() => onColumns('participant')} title="모든 layer를 process 단위로 펼침">Process</button>
        </div>
        <span className="grow" />
        <span className="legend-mini">
          {Object.entries(HANDOFF).map(([k, v]) => <span key={k} className="legend-item"><svg width="18" height="6"><line x1="0" y1="3" x2="18" y2="3" stroke={v.color} strokeWidth="2" strokeDasharray={DASHED.has(k) ? '4 3' : undefined} /></svg>{v.label}</span>)}
          <span className="legend-item" title="Pipeline timing에도 같은 이름으로 나오는 단계">★ Pipeline</span><span className="legend-item">Δ 대기</span>
        </span>
      </div>
      <LoopStrip doc={doc} active={active} onPick={(cad) => { const f = doc.flows.find((x) => x.cadence === cad); if (f) onFlow(f.id) }} />
      <Summary doc={doc} lay={lay} all={all} source={source} />
      <Sequence doc={doc} lay={lay} canOpen={canOpen} onOpen={onOpen} onLayer={toggleLayer} />
    </div>
  )
}

/** Every loop of the scenario, fastest first, and where one loop hands work to another. */
function LoopStrip({ doc, active, onPick }: { doc: HandoffDoc; active: string | null; onPick: (cad: string) => void }) {
  const cads = [...doc.cadences].sort((a, b) => (cadencePeriod(doc, a.id) ?? Infinity) - (cadencePeriod(doc, b.id) ?? Infinity))
  const links = cadenceLinks(doc)
  const name = (id: string) => cadenceLabel(doc, id)
  return (
    <div className="handoff-cadences">
      <span className="lbl">Loops</span>
      {cads.map((c) => {
        const hasFlow = doc.flows.some((f) => f.cadence === c.id)
        return (
          <button key={c.id} className={`cad-chip k-${c.kind}${c.id === active ? ' on' : ''}`} disabled={!hasFlow} onClick={() => onPick(c.id)}
            title={`${c.name} · ${loopKind(doc, c.id)}${c.note ? ` · ${c.note}` : ''}${hasFlow ? '' : ' (이 주기로 시작하는 처리 단위 없음 · 다른 단위 안의 단계로만 나옴)'}`}>
            <b>{c.name}</b> <span className="mono">{fmtHz(cadencePeriod(doc, c.id))}</span> <span className="faint">{loopKind(doc, c.id)}</span>
          </button>)
      })}
      {links.length > 0 && <span className="handoff-links">{links.map((l) => <span key={`${l.from}>${l.to}`} title={`${l.n} hand-off`}>
        {name(l.from)} <b>→</b> {name(l.to)}{l.via.length > 0 && <span className="faint"> via {l.via.slice(0, 2).join(', ')}</span>}</span>)}</span>}
    </div>
  )
}

function Summary({ doc, lay, all, source }: { doc: HandoffDoc; lay: FlowLayout; all: boolean; source: string }) {
  const ms = (v: number | null) => (v === null ? '—' : `${v.toFixed(1)} ms`)
  const steps = lay.rows.reduce((a, r) => a + (r.kind === 'call' ? r.folded?.length ?? 1 : 0), 0)
  if (all) {
    const kinds = new Map<string, number>()
    for (const l of lay.loops) { const k = loopKind(doc, l.flow.cadence); kinds.set(k, (kinds.get(k) ?? 0) + 1) }
    return (
      <div className="behavior-status handoff-summary">
        <span><b>{lay.loops.length}</b> loops — {[...kinds.entries()].map(([k, n]) => `${k} ${n}`).join(' · ')}</span>
        <span className="faint">loop끼리는 buffer · queue · timestamp로만 만나고 서로를 기다리지 않음 (Loops 줄의 → 참고)</span>
        <span className="faint">{steps} 단계 · {lay.columns.length} 열 · {source}</span>
      </div>
    )
  }
  const flow = lay.loops[0].flow
  return (
    <div className="behavior-status handoff-summary">
      {flow.summary && <span>{flow.summary}</span>}
      <span className="mono">end-to-end {ms(lay.e2e)}</span>
      {lay.lead !== null && <span className="mono" title="몇 단위 앞서 시작한 단계(예: camera request n−4)까지의 선행 시간">선행 {ms(lay.lead)}</span>}
      {lay.inFlight !== null && <span title="end-to-end ÷ 주기: 이 단위가 끝나기 전에 시작되는 다음 단위 수">동시에 <b>{lay.inFlight}</b> 단위 진행 ({cadenceLabel(doc, flow.cadence)} · {loopKind(doc, flow.cadence)})</span>}
      <span className="mono">HW {lay.hw.toFixed(1)} · SW {lay.sw.toFixed(1)} ms</span>
      <span className="faint">{steps} 단계 · {lay.columns.length} 열 · {source}</span>
    </div>
  )
}


const ROW = 32, NOTE = 26, BAND = 20, HEAD = 58, PAD = 24
// The # · Δ gutter (left) and the t · rate gutter (right) stay in view while the lanes scroll sideways.
const LEFT = 84, T_W = 58
const chars = (s: string) => [...s].reduce((a, c) => a + (c.charCodeAt(0) > 0x2e80 ? 11 : 6.3), 0)
const badgeW = (text: string) => chars(text) + 14
const DEPTH: Record<Frame['kind'], number> = { loop: 0, par: 1, sub: 2 }
type CallRow = Extract<FlowLayout['rows'][number], { kind: 'call' }>

/** What a call row is called, as on the timelines (SENSOR_REAR, HAL_REQUEST), and its hand-off kind. */
function describe(r: CallRow) {
  const s: HandoffStep = r.step
  const kind = s.handoff && HANDOFF[s.handoff] ? s.handoff : 'data'
  const last = r.folded?.[r.folded.length - 1]
  const name = last ? `${stepName(s)} → ${stepName(last)}` : stepName(s)
  const detail = last ? `${r.folded!.length} 단계` : s.call && s.call !== name ? s.call : ''
  return { s, kind, last, name, detail }
}
type Place = { tx: number; anchor: 'start' | 'middle' | 'end'; lo: number; hi: number }
/** Where a call row's label goes and the x range it covers; `right` is the lanes' right edge. */
function placeLabel(r: CallRow, x: (c: number) => number, colW: number, right: number): Place {
  const { name, detail } = describe(r)
  const w = chars(`★ ${name} ${detail} 00.00`) * 0.95
  const x2 = x(r.to)
  const at = (tx: number, anchor: Place['anchor']): Place =>
    ({ tx, anchor, lo: anchor === 'start' ? tx : anchor === 'end' ? tx - w : tx - w / 2, hi: anchor === 'start' ? tx + w : anchor === 'end' ? tx : tx + w / 2 })
  if (r.from === null || r.from === r.to) {
    // labels next to the last column go left of its lifeline, clear of the start marker (·→) when the row starts the unit
    if (right - x2 - 34 > w) return at(x2 + (r.from === null ? 9 : 30), 'start')
    return at(x2 - (r.from === null ? 44 : 10), 'end')
  }
  const x1 = x(r.from)
  return Math.abs(x2 - x1) < colW * 1.2 ? at(Math.min(x1, x2) + 6, 'start') : at((x1 + x2) / 2, 'middle')
}
const noteW = (x1: number, x2: number, text: string) => Math.max(x2 - x1, chars(text) + 20)
/** Right end of a loop / par / sub-loop title, from the frame's left edge. */
function frameTitleW(f: Frame, doc: HandoffDoc) {
  const tabW = (f.kind === 'par' ? 3 : 4) * 7 + 14
  const text = f.kind === 'par' ? Math.max(0, ...(f.segments ?? []).map((s) => chars(`[${s.label}]`)))
    : chars(`[${f.label}] ${f.tag ?? loopKind(doc, f.cadence)}${f.note ? `  ${f.note}` : ''}`) * (f.kind === 'loop' ? 1.05 : 1)
  return DEPTH[f.kind] * 6 + tabW + 14 + text + 8
}
function rowTitle(r: CallRow, open: boolean) {
  const { s, kind, last, name } = describe(r)
  return [`#${r.n} ${name}`, ...(r.folded ?? []).map((f) => `  · ${stepName(f)}${f.call ? ` (${f.call})` : ''} ${(f.dur_ms ?? 0).toFixed(2)} ms`),
    !last && s.call && `call ${s.call}`, s.task && `trace 이름 ${s.task}`, s.slice && `slice ${s.slice}`, s.node && 'Pipeline timing에도 같은 이름', `hand-off ${kind}`,
    s.t_ms !== undefined && `t ${s.t_ms.toFixed(3)} ms · 실행 ${(s.dur_ms ?? 0).toFixed(3)} ms`, open && '클릭: Full-stack timing에서 열기'].filter(Boolean).join('\n')
}

function Sequence({ doc, lay, canOpen, onOpen, onLayer }: { doc: HandoffDoc; lay: FlowLayout; canOpen?: (slice: string) => boolean; onOpen?: (slice: string) => void; onLayer: (layer: string) => void }) {
  const colW = lay.columns.length <= 6 ? 176 : 136
  // Labels, notes and loop titles may reach past the lanes (one-column flows, long notes): the lanes widen on
  // both sides so nothing ends up under the sticky gutters.
  const laneW = lay.columns.length * colW + PAD
  const base = (c: number) => c * colW + colW / 2
  let lo = 0, hi = laneW
  for (const r of lay.rows) {
    if (r.kind === 'note') {
      const m = (base(r.from) + base(r.to)) / 2, w = noteW(base(r.from) - colW * 0.42, base(r.to) + colW * 0.42, r.step.note ?? '')
      lo = Math.min(lo, m - w / 2 - 4); hi = Math.max(hi, m + w / 2 + 4)
    } else {
      const p = placeLabel(r, base, colW, laneW)
      lo = Math.min(lo, p.lo - 6, base(r.to) - 40); hi = Math.max(hi, p.hi + 8)
    }
  }
  for (const f of lay.frames) hi = Math.max(hi, 4 + frameTitleW(f, doc))
  const OX = Math.ceil(-lo)
  const x = (c: number) => OX + base(c)
  const right = OX + laneW
  const W = Math.ceil(OX + hi)
  const RW = Math.max(132, T_W + Math.max(0, ...lay.rows.map((r) => (r.kind === 'call' ? r.badges.reduce((a, b) => a + badgeW(b.text) + 4, 0) : 0))) + 8)
  // vertical positions: every frame start (and par branch change) takes a header band above its first row
  const bands = new Map<number, number>()
  const addBand = (i: number) => bands.set(i, (bands.get(i) ?? 0) + 1)
  for (const f of lay.frames) { addBand(f.start); for (const s of (f.segments ?? []).slice(1)) addBand(s.start) }
  const ends = new Map<number, number>()
  for (const f of lay.frames) ends.set(f.end, (ends.get(f.end) ?? 0) + 1)
  const ys: number[] = [], tops: number[] = []
  let y = 8
  lay.rows.forEach((r, i) => {
    y += (bands.get(i) ?? 0) * BAND
    tops.push(y)
    const h = r.kind === 'note' ? NOTE : ROW
    ys.push(y + h / 2)
    y += h + (ends.get(i) ?? 0) * 6
  })
  const H = y + 10
  const rowH = (i: number) => (lay.rows[i].kind === 'note' ? NOTE : ROW)
  // band slot of a frame at its start row: outer frames sit higher
  const slotOf = (f: Frame) => lay.frames.filter((g) => g.start === f.start && DEPTH[g.kind] < DEPTH[f.kind]).length
    + lay.frames.filter((g) => g.segments?.slice(1).some((s) => s.start === f.start)).length
  const frameRect = (f: Frame) => {
    const nBand = bands.get(f.start) ?? 0, inset = DEPTH[f.kind] * 6
    const top = tops[f.start] - (nBand - slotOf(f)) * BAND
    const bottom = ys[f.end] + rowH(f.end) / 2 + 3 + (lay.frames.filter((g) => g.end === f.end && DEPTH[g.kind] > DEPTH[f.kind]).length) * 6
    return { x1: OX + 4 + inset, x2: OX + lay.columns.length * colW - 4 - inset, top, bottom }
  }
  const openOf = (r: CallRow) => (r.step.slice && canOpen?.(r.step.slice) ? () => onOpen?.(r.step.slice!) : undefined)
  const zebra = (w: number) => lay.rows.map((r, i) => r.kind === 'call' && (i % 2 || r.offRate)
    ? <rect key={`bg${i}`} x={0} y={ys[i] - rowH(i) / 2} width={w} height={rowH(i)} fill={r.offRate ? '#FBF3E4' : '#F8F5F0'} /> : null)
  // a gutter cell answers to the same hover title and click as its row in the lanes
  const gutter = (w: number, cell: (r: CallRow, y: number) => ReactNode) => lay.rows.map((r, i) => {
    if (r.kind !== 'call') return null
    const open = openOf(r)
    return <g key={i} style={open ? { cursor: 'pointer' } : undefined} onClick={open}><title>{rowTitle(r, !!open)}</title>
      <rect x={0} y={ys[i] - ROW / 2} width={w} height={ROW} fill="transparent" />{cell(r, ys[i])}</g>
  })
  return (
    <div className="handoff-seq">
      <div className="handoff-head">
        <svg className="handoff-gut" width={LEFT} height={HEAD} role="presentation"><text x={10} y={50} fontSize={10} fill="#6B6558"># · 대기 Δ</text></svg>
        <svg width={W} height={HEAD} role="presentation">
          {layerBands(lay).map((b) => {
            const span = lay.layers.find((l) => l.layer === b.layer)
            const can = !!span && span.parts > 1
            const name = LAYER_LABEL[b.layer] ?? b.layer
            const label = !can ? name : span.expanded ? `▾ ${name}` : `▸ ${name} · ${span.parts}`
            const toggle = can ? () => onLayer(b.layer) : undefined
            return <g key={b.i} className={can ? 'handoff-layer' : undefined} role={can ? 'button' : undefined} tabIndex={can ? 0 : undefined} aria-expanded={can ? span.expanded : undefined}
              onClick={toggle} onKeyDown={toggle && ((e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle() } })}>
              {can && <title>{span.expanded ? `${name}: 한 열로 접기` : `${name}: process ${span.parts}개로 펼치기`}</title>}
              <rect x={OX + b.i * colW + 3} y={3} width={(b.j - b.i + 1) * colW - 6} height={16} rx={3} fill={layerColor(b.layer) ?? '#ccc'} opacity={0.2} />
              <text x={OX + ((b.i + b.j + 1) / 2) * colW} y={15} fontSize={10.5} fontWeight={600} textAnchor="middle" fill="#3B3F4A">{label}</text></g>
          })}
          {lay.columns.map((c, i) => <g key={i}>
            <rect x={x(i) - colW / 2 + 6} y={23} width={colW - 12} height={32} rx={5} fill="#fff" stroke={layerColor(c.layer) ?? '#bbb'} />
            <text x={x(i)} y={37} fontSize={11.5} fontWeight={600} textAnchor="middle" fill="#1F2430"><title>{c.title}</title>{clip(c.title, colW / 7.2)}</text>
            <text x={x(i)} y={50} fontSize={9.5} textAnchor="middle" fill="#6B6558"><title>{c.sub}</title>{clip(c.sub, colW / 5.6)}</text></g>)}
        </svg>
        <svg className="handoff-rate" width={RW} height={HEAD} role="presentation">
          <text x={10} y={50} fontSize={10} fill="#6B6558">t ms</text><text x={T_W} y={50} fontSize={10} fill="#6B6558">rate · unit</text></svg>
      </div>
      <div className="handoff-body">
        <svg className="handoff-gut" width={LEFT} height={H} role="presentation">
          {zebra(LEFT)}
          {gutter(LEFT, (r, yy) => <>
            <circle cx={16} cy={yy} r={9} fill="#3B3F4A" /><text x={16} y={yy + 3.5} fontSize={9.5} fontWeight={700} textAnchor="middle" fill="#fff">{r.n}</text>
            {r.wait !== null && <text x={32} y={yy + 4} fontSize={10.5} fontFamily="var(--mono)" fill={r.wait > 2 ? '#9A5B13' : '#8A8274'}>Δ{r.wait.toFixed(2)}</text>}</>)}
        </svg>
        <svg width={W} height={H} role="img" aria-label="Processing flow sequence" overflow="visible">
          <defs>{Object.entries(HANDOFF).map(([k, v]) => <marker key={k} id={`ho-${k}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill={v.color} /></marker>)}</defs>
          {zebra(W)}
          {[...lay.frames].sort((a, b) => DEPTH[a.kind] - DEPTH[b.kind]).map((f, k) => <FrameG key={k} f={f} r={frameRect(f)} doc={doc} slotTop={(i) => tops[i] - BAND} />)}
          {lay.columns.map((_, i) => <line key={i} x1={x(i)} x2={x(i)} y1={0} y2={H} stroke="#D6CFC4" strokeDasharray="3 4" />)}
          {lay.rows.map((r, i) => r.kind === 'note' ? <NoteRow key={i} y={ys[i]} x1={x(r.from) - colW * 0.42} x2={x(r.to) + colW * 0.42} text={r.step.note ?? ''} />
            : <CallRowG key={i} r={r} y={ys[i]} x={x} W={W} right={right} h={ROW} colW={colW} bar={layerColor(lay.columns[r.to].layer) ?? '#8C8574'} open={openOf(r)} />)}
        </svg>
        <svg className="handoff-rate" width={RW} height={H} role="presentation">
          {zebra(RW)}
          {gutter(RW, (r, yy) => {
            let bx = T_W
            return <>
              {r.step.t_ms !== undefined && <text x={10} y={yy + 4} fontSize={10.5} fontFamily="var(--mono)" fill="#3B3F4A">{r.step.t_ms.toFixed(2)}</text>}
              {r.badges.map((b) => { const w = badgeW(b.text); const g = <g key={b.text}><rect x={bx} y={yy - 9} width={w} height={18} rx={9} fill={b.tone === 'cadence' ? '#F6E3BF' : b.tone === 'every' ? '#E3EEEB' : '#E7ECF5'} />
                <text x={bx + 7} y={yy + 4} fontSize={10.5} fill="#3B3F4A">{b.text}</text></g>; bx += w + 4; return g })}</>
          })}
        </svg>
      </div>
    </div>
  )
}

function FrameG({ f, r, doc, slotTop }: { f: Frame; r: { x1: number; x2: number; top: number; bottom: number }; doc: HandoffDoc; slotTop: (i: number) => number }) {
  const kind = doc.cadences.find((c) => c.id === f.cadence)?.kind ?? 'frame'
  const tone = f.kind === 'par' ? { stroke: '#9A927F', tab: '#EEE8DD' } : FRAME_TONE[kind] ?? FRAME_TONE.frame
  const word = f.kind === 'par' ? 'par' : 'loop'
  const tabW = word.length * 7 + 14
  const strokeW = f.kind === 'loop' ? 1.6 : 1.1
  return <g>
    <rect x={r.x1} y={r.top} width={r.x2 - r.x1} height={r.bottom - r.top} rx={4} fill="none" stroke={tone.stroke} strokeWidth={strokeW} strokeDasharray={f.kind === 'par' ? undefined : tone.dash} />
    <path d={`M${r.x1},${r.top + 15} h${tabW} l6,-6 v-9 h-${tabW + 6} z`} fill={tone.tab} stroke={tone.stroke} strokeWidth={1} />
    <text x={r.x1 + 6} y={r.top + 12} fontSize={10} fontWeight={700} fill="#3B3F4A">{word}</text>
    {f.kind === 'par'
      ? f.segments!.map((s, j) => { const sy = j === 0 ? r.top : slotTop(s.start)
          return <g key={s.label}>{j > 0 && <line x1={r.x1} x2={r.x2} y1={sy + 2} y2={sy + 2} stroke={tone.stroke} strokeDasharray="5 4" />}
            <text x={r.x1 + tabW + 14} y={sy + 13} fontSize={10.5} fontWeight={600} fill="#4A4F5A">[{s.label}]</text></g> })
      : <text x={r.x1 + tabW + 14} y={r.top + 13} fontSize={f.kind === 'loop' ? 11.5 : 10.5} fontWeight={f.kind === 'loop' ? 700 : 600} fill="#3B3F4A">
          [{f.label}] <tspan fontWeight={500} fill={tone.stroke}>{f.tag}</tspan>{f.note && <tspan fontWeight={400} fill="#6B6558" fontFamily="var(--mono)" fontSize={10}>  {f.note}</tspan>}</text>}
  </g>
}

function layerBands(lay: FlowLayout) {
  const out: { layer: string; i: number; j: number }[] = []
  lay.columns.forEach((c, i) => { const b = out[out.length - 1]; if (b && b.layer === c.layer) b.j = i; else out.push({ layer: c.layer, i, j: i }) })
  return out
}
const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, Math.max(1, Math.floor(n) - 1))}…` : s)

function NoteRow({ y, x1, x2, text }: { y: number; x1: number; x2: number; text: string }) {
  // Sequence widens the lanes to fit a note wider than its columns, so the note stays centred on them
  const w = noteW(x1, x2, text)
  const cx = (x1 + x2) / 2
  return <g><rect x={cx - w / 2} y={y - 10} width={w} height={20} rx={3} fill="#FFF6D6" stroke="#E2CC7E" />
    <text x={cx} y={y + 4} fontSize={11} textAnchor="middle" fill="#5B4A12">{text}</text></g>
}

function CallRowG({ r, y, x, W, right, h, open, colW, bar }: { r: CallRow; y: number; x: (c: number) => number; W: number; right: number; h: number; open?: () => void; colW: number; bar: string }) {
  const { s, kind, last, name, detail } = describe(r)
  const color = HANDOFF[kind].color, dash = DASHED.has(kind) ? '5 3' : undefined
  const x2 = x(r.to)
  // name as on the timelines (SENSOR_REAR, HAL_REQUEST); the call the trace recorded follows it, faint
  const dur = last && s.t_ms !== undefined && last.t_ms !== undefined ? last.t_ms + (last.dur_ms ?? 0) - s.t_ms : s.dur_ms
  const label = <>
    {s.node && <tspan fill="#B7791F">★ </tspan>}{name}
    {detail && <tspan fontSize={10} fill="#8A8274"> {detail}</tspan>}
    {dur !== undefined && <tspan fontFamily="var(--mono)" fontSize={10} fill="#6B6558"> {dur.toFixed(2)}</tspan>}
  </>
  const halo = { paintOrder: 'stroke' as const, stroke: '#fff', strokeWidth: 3 }
  const p = placeLabel(r, x, colW, right)
  const text = (yy: number) => <text x={p.tx} y={yy} fontSize={11.5} textAnchor={p.anchor} fill="#1F2430" style={halo}>{label}</text>
  let arrow
  if (r.from === null) arrow = <g><circle cx={x2 - 34} cy={y} r={3.5} fill={color} /><line x1={x2 - 30} y1={y} x2={x2 - 7} y2={y} stroke={color} strokeWidth={1.5} markerEnd={`url(#ho-${kind})`} />
    {text(y - 5)}</g>
  else if (r.from === r.to) arrow = <g><path d={`M${x2 + 5},${y - 8} h20 v13 h-15`} fill="none" stroke={color} strokeWidth={1.4} strokeDasharray={dash} markerEnd={`url(#ho-${kind})`} />
    {text(y + 1)}</g>
  else {
    const x1 = x(r.from), dir = x2 > x1 ? 1 : -1
    arrow = <g><line x1={x1 + dir * 4} y1={y + 3} x2={x2 - dir * 6} y2={y + 3} stroke={color} strokeWidth={1.5} strokeDasharray={dash} markerEnd={`url(#ho-${kind})`} />
      {text(y - 4)}</g>
  }
  return (
    <g style={open ? { cursor: 'pointer' } : undefined} onClick={open}>
      <title>{rowTitle(r, !!open)}</title>
      <rect x={0} y={y - h / 2} width={W} height={h} fill="transparent" />
      {arrow}
      <rect x={x2 - 4} y={y - 8} width={8} height={16} rx={2} fill={bar} />
    </g>
  )
}