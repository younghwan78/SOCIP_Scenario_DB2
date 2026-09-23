import { useEffect, useMemo, useRef, useState } from 'react'
import { frameStarts, neighbours, sliceColor, type Slice, type Timeline } from '../lib/timeline'

const LABEL_W = 220
const ROW = 22
const HEAD = 44

interface Props {
  timeline: Timeline
  width: number
  selectedSlice: string | null
  highlightNode: string | null
  showFlows: boolean
  onSelect: (s: Slice | null) => void
}

function niceStep(span: number): number {
  const raw = span / 10
  const p = Math.pow(10, Math.floor(Math.log10(raw)))
  return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) ?? raw
}

export function TimelineView({ timeline, width, selectedSlice, highlightNode, showFlows, onSelect }: Props) {
  const initial: [number, number] = [timeline.start, Math.min(timeline.end, timeline.start + 100)]
  const [range, setRange] = useState<[number, number]>(initial)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const ref = useRef<SVGSVGElement>(null)
  useEffect(() => { setRange([timeline.start, Math.min(timeline.end, timeline.start + 100)]) }, [timeline])

  const [t0, t1] = range
  const plotW = Math.max(200, width - LABEL_W - 12)
  const x = (t: number) => LABEL_W + ((t - t0) / (t1 - t0)) * plotW

  const rows = useMemo(() => {
    const out: { kind: 'group' | 'track'; id: string; name: string; group: string; y: number }[] = []
    let y = HEAD
    for (const g of timeline.groups) {
      out.push({ kind: 'group', id: `g:${g.name}`, name: g.name, group: g.name, y }); y += ROW
      if (collapsed.has(g.name)) continue
      for (const t of g.tracks) { out.push({ kind: 'track', id: t.id, name: t.name, group: g.name, y }); y += ROW }
    }
    return { list: out, height: y + 8 }
  }, [timeline, collapsed])
  const yOf = useMemo(() => {
    const m = new Map<string, number>()
    rows.list.forEach((r) => { if (r.kind === 'track') m.set(r.id, r.y) })
    // collapsed groups: slices collapse onto the group row
    rows.list.forEach((r) => { if (r.kind === 'group' && collapsed.has(r.name)) timeline.groups.find((g) => g.name === r.name)?.tracks.forEach((t) => m.set(t.id, r.y)) })
    return m
  }, [rows, collapsed, timeline])

  const byId = useMemo(() => new Map(timeline.slices.map((s) => [s.id, s])), [timeline])
  const focus = useMemo(() => (selectedSlice ? neighbours(timeline, selectedSlice) : new Set<string>()), [timeline, selectedSlice])
  const visible = timeline.slices.filter((s) => s.end >= t0 && s.start <= t1 && yOf.has(s.track))
  const step = niceStep(t1 - t0)
  const ticks: number[] = []
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) ticks.push(+t.toFixed(6))

  const zoomAt = (factor: number, center = (t0 + t1) / 2) => {
    const span = Math.min(Math.max((t1 - t0) * factor, 0.5), Math.max(timeline.end - timeline.start, 1) * 1.2)
    const a = center - (center - t0) * (span / (t1 - t0))
    setRange([a, a + span])
  }
  const pan = (frac: number) => { const d = (t1 - t0) * frac; setRange([t0 + d, t1 + d]) }
  const onKey = (e: React.KeyboardEvent) => {
    const k = e.key.toLowerCase()
    if (k === 'w') zoomAt(0.7); else if (k === 's') zoomAt(1.4); else if (k === 'a') pan(-0.2); else if (k === 'd') pan(0.2); else return
    e.preventDefault()
  }
  const onWheel = (e: React.WheelEvent) => {
    if (!e.ctrlKey && !e.shiftKey) return
    e.preventDefault()
    const rect = ref.current?.getBoundingClientRect()
    const center = rect ? t0 + ((e.clientX - rect.left - LABEL_W) / plotW) * (t1 - t0) : undefined
    if (e.shiftKey) pan(e.deltaY > 0 ? 0.1 : -0.1); else zoomAt(e.deltaY > 0 ? 1.25 : 0.8, center)
  }

  return (
    <div tabIndex={0} onKeyDown={onKey} onWheel={onWheel} style={{ outline: 'none' }} aria-label="Timeline (W/S zoom, A/D pan)">
      <svg ref={ref} width={width} height={rows.height} role="img" aria-label="Timeline" onClick={() => onSelect(null)} style={{ display: 'block' }}>
        <defs>
          <marker id="f-hi" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#174D47" /></marker>
          <marker id="f-lo" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="#9A9184" /></marker>
          <clipPath id="plot"><rect x={LABEL_W} y={0} width={plotW + 12} height={rows.height} /></clipPath>
        </defs>
        <rect x={0} y={0} width={LABEL_W} height={rows.height} fill="var(--surface-soft)" />
        <line x1={LABEL_W} y1={0} x2={LABEL_W} y2={rows.height} stroke="var(--line)" />
        <text x={10} y={28} fontSize={10.5} fill="var(--faint)">{`${t0.toFixed(1)} – ${t1.toFixed(1)} ms`}</text>
        <g clipPath="url(#plot)">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x(t)} y1={24} x2={x(t)} y2={36} stroke="#B9B0A2" />
              <text x={x(t) + 3} y={33} fontSize={9.5} fill="var(--muted)" fontFamily="var(--mono)">{t}ms</text>
              <line x1={x(t)} y1={HEAD} x2={x(t)} y2={rows.height} stroke="#F4F0EA" />
            </g>
          ))}
          {frameStarts(timeline).map(({ frame, t }) => (
            <g key={frame}>
              <line x1={x(t)} y1={4} x2={x(t)} y2={rows.height} stroke="var(--primary)" strokeDasharray="3 3" opacity={0.5} />
              <path d={`M${x(t)} 4 h26 l-5 5 l5 5 h-26z`} fill="var(--primary)" />
              <text x={x(t) + 3} y={13} fontSize={9} fill="#fff" fontWeight={700}>f{frame}</text>
            </g>
          ))}
        </g>
        {rows.list.map((r) => r.kind === 'group' ? (
          <g key={r.id} style={{ cursor: 'pointer' }} onClick={(e) => { e.stopPropagation(); setCollapsed((c) => { const s = new Set(c); if (s.has(r.name)) s.delete(r.name); else s.add(r.name); return s }) }}>
            <rect x={0} y={r.y} width={width} height={ROW} fill="#F3EFE8" />
            <text x={10} y={r.y + 15} fontSize={11.5} fontWeight={700} fill="var(--text-2)">{collapsed.has(r.name) ? '▸' : '▾'} {r.name}</text>
          </g>
        ) : (
          <g key={r.id}>
            <text x={24} y={r.y + 15} fontSize={11} fill="#4A4F5A">{r.name}</text>
            <line x1={0} y1={r.y + ROW} x2={width} y2={r.y + ROW} stroke="#F1ECE4" />
          </g>
        ))}
        <g clipPath="url(#plot)">
          {visible.map((s) => {
            const y = yOf.get(s.track)!
            const sx = x(s.start), w = Math.max(x(s.end) - sx, 1.5)
            const isSel = s.id === selectedSlice
            const hot = isSel || (highlightNode !== null && s.nodeId === highlightNode) || focus.has(s.id)
            const dimmed = (selectedSlice !== null || highlightNode !== null) && !hot
            return (
              <g key={s.id} style={{ cursor: 'pointer' }} opacity={dimmed ? 0.45 : 1} onClick={(e) => { e.stopPropagation(); onSelect(s) }}>
                <rect x={sx} y={y + 3} width={w} height={ROW - 6} rx={2} fill={sliceColor(s.group)}
                  stroke={isSel ? '#174D47' : hot ? '#2F6F68' : 'rgba(0,0,0,0.08)'} strokeWidth={isSel ? 2.2 : hot ? 1.4 : 1} />
                {w > 40 && <text x={sx + 4} y={y + 15} fontSize={10} fill="#2B2F38" fontFamily="var(--mono)">{s.label}{s.frame !== null ? ` f${s.frame}` : ''}</text>}
                <title>{`${s.label} · f${s.frame ?? '-'}\n${s.start.toFixed(3)} – ${s.end.toFixed(3)} ms (${(s.end - s.start).toFixed(3)} ms)`}</title>
              </g>
            )
          })}
          {showFlows && timeline.flows.map((f) => {
            const a = byId.get(f.from), b = byId.get(f.to)
            if (!a || !b || !yOf.has(a.track) || !yOf.has(b.track)) return null
            if (a.end < t0 && b.start < t0) return null
            if (a.end > t1 && b.start > t1) return null
            const hi = selectedSlice !== null && (f.from === selectedSlice || f.to === selectedSlice)
            const y1 = yOf.get(a.track)! + ROW / 2, y2 = yOf.get(b.track)! + ROW / 2
            if (a.track === b.track) return null
            // Streaming (OTF) successors start before the predecessor ends: anchor start-to-start.
            const x1 = b.start < a.end ? x(a.start) + 3 : x(a.end), x2 = x(b.start), dx = Math.max(14, Math.abs(x2 - x1) / 2)
            return <path key={`${f.from}>${f.to}`} d={`M${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`} fill="none"
              stroke={hi ? '#174D47' : '#9A9184'} strokeWidth={hi ? 1.8 : 1} opacity={selectedSlice && !hi ? 0.25 : 0.85} markerEnd={`url(#${hi ? 'f-hi' : 'f-lo'})`} />
          })}
        </g>
      </svg>
      <div style={{ display: 'flex', gap: 8, padding: '6px 12px', borderTop: '1px solid var(--line-soft)', alignItems: 'center' }}>
        <button className="btn" onClick={() => zoomAt(0.7)} aria-label="확대">＋</button>
        <button className="btn" onClick={() => zoomAt(1.4)} aria-label="축소">－</button>
        <button className="btn" onClick={() => pan(-0.25)}>◀</button>
        <button className="btn" onClick={() => pan(0.25)}>▶</button>
        <button className="btn" onClick={() => setRange([timeline.start, timeline.end])}>전체</button>
        <button className="btn" onClick={() => setRange(initial)}>0–100 ms</button>
        <span className="mono faint" style={{ fontSize: 11 }}>W/S zoom · A/D pan · Ctrl+wheel zoom · Shift+wheel pan</span>
      </div>
    </div>
  )
}
