import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { frameStarts, neighbours, sliceColor, type Slice, type Timeline } from '../lib/timeline'

const LABEL_W = 150
const ROW = 22
const HEAD = 34

interface Props {
  timeline: Timeline
  selectedSlice: string | null
  highlightNode: string | null
  showFlows: boolean
  onSelect: (s: Slice | null) => void
  colorBy?: 'group' | 'frame'
}

export const FRAME_COLORS = ['#F4A76E', '#7DB9E8', '#9AD08F', '#D7A6E8', '#F2D16B', '#86D3C7']

function niceStep(span: number): number {
  const raw = span / 8
  const p = Math.pow(10, Math.floor(Math.log10(raw)))
  return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) ?? raw
}

/**
 * Perfetto-style track view. Ruler stays fixed, tracks scroll vertically.
 * wheel = vertical scroll · Ctrl+wheel = zoom at cursor · Shift+wheel / drag = horizontal pan · W/S/A/D.
 */
export function TimelineView({ timeline, selectedSlice, highlightNode, showFlows, onSelect, colorBy = 'group' }: Props) {
  const defaultRange = useCallback((): [number, number] => [timeline.start, Math.min(timeline.end, timeline.start + 100)], [timeline])
  const [range, setRange] = useState<[number, number]>(defaultRange)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const rootRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(800)
  useEffect(() => { setRange(defaultRange()) }, [defaultRange])
  useLayoutEffect(() => {
    const el = rootRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(360, Math.floor(e.contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const [t0, t1] = range
  const plotW = Math.max(160, width - LABEL_W - 10)
  const x = (t: number) => LABEL_W + ((t - t0) / (t1 - t0)) * plotW
  const full = Math.max(timeline.end - timeline.start, 1)

  const setClamped = useCallback((a: number, span: number) => {
    const s = Math.min(Math.max(span, 0.2), full * 1.2)
    const lo = timeline.start - s * 0.5, hi = timeline.end - s * 0.5
    const a2 = Math.min(Math.max(a, lo), hi)
    setRange([a2, a2 + s])
  }, [full, timeline])
  const zoomAt = useCallback((factor: number, center?: number) => {
    setRange(([a, b]) => {
      const c = center ?? (a + b) / 2
      const s = Math.min(Math.max((b - a) * factor, 0.2), full * 1.2)
      const na = c - (c - a) * (s / (b - a))
      return [na, na + s]
    })
  }, [full])
  const pan = useCallback((frac: number) => setRange(([a, b]) => { const d = (b - a) * frac; return [a + d, b + d] }), [])

  const rows = useMemo(() => {
    const out: { kind: 'group' | 'track'; id: string; name: string; group: string; y: number }[] = []
    let y = 0
    for (const g of timeline.groups) {
      out.push({ kind: 'group', id: `g:${g.name}`, name: g.name, group: g.name, y }); y += ROW
      if (collapsed.has(g.name)) continue
      for (const t of g.tracks) { out.push({ kind: 'track', id: t.id, name: t.name, group: g.name, y }); y += ROW }
    }
    return { list: out, height: y + 6 }
  }, [timeline, collapsed])
  const yOf = useMemo(() => {
    const m = new Map<string, number>()
    rows.list.forEach((r) => { if (r.kind === 'track') m.set(r.id, r.y) })
    rows.list.forEach((r) => { if (r.kind === 'group' && collapsed.has(r.name)) timeline.groups.find((g) => g.name === r.name)?.tracks.forEach((t) => m.set(t.id, r.y)) })
    return m
  }, [rows, collapsed, timeline])

  const byId = useMemo(() => new Map(timeline.slices.map((s) => [s.id, s])), [timeline])
  const focus = useMemo(() => (selectedSlice ? neighbours(timeline, selectedSlice) : new Set<string>()), [timeline, selectedSlice])
  const visible = timeline.slices.filter((s) => s.end >= t0 && s.start <= t1 && yOf.has(s.track))
  const step = niceStep(t1 - t0)
  const ticks: number[] = []
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) ticks.push(+t.toFixed(6))
  const flags = frameStarts(timeline)

  // Bring an externally selected slice (graph node click) into the visible range and scroll its row into view.
  useEffect(() => {
    if (!selectedSlice) return
    const s = byId.get(selectedSlice)
    if (!s) return
    const [a, b] = range
    if (s.end < a || s.start > b) setClamped(s.start - (b - a) * 0.2, b - a)
    const y = yOf.get(s.track)
    const body = bodyRef.current
    if (body && y !== undefined && (y < body.scrollTop || y + ROW > body.scrollTop + body.clientHeight)) body.scrollTop = Math.max(0, y - body.clientHeight / 3)
  }, [selectedSlice]) // eslint-disable-line react-hooks/exhaustive-deps

  // Native wheel (non-passive): Ctrl/⌘ zoom and Shift pan must not trigger browser zoom / page scroll.
  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      const r = el.getBoundingClientRect()
      const px = e.clientX - r.left - LABEL_W
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault()
        setRange(([a, b]) => {
          const c = a + (Math.min(Math.max(px, 0), plotW) / plotW) * (b - a)
          const s = Math.min(Math.max((b - a) * Math.exp(e.deltaY * 0.0025), 0.2), full * 1.2)
          const na = c - (c - a) * (s / (b - a))
          return [na, na + s]
        })
      } else if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        e.preventDefault()
        const d = e.shiftKey ? e.deltaY : e.deltaX
        setRange(([a, b]) => { const k = ((b - a) / plotW) * d; return [a + k, b + k] })
      }
      else {
        // plain vertical wheel scrolls the tracks only (never the page behind it)
        e.preventDefault()
        if (bodyRef.current) bodyRef.current.scrollTop += e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [plotW, full])

  const drag = useRef<{ px: number; a: number; b: number; moved: boolean; id: number } | null>(null)
  const suppress = useRef(false)
  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return
    rootRef.current?.focus({ preventScroll: true })
    drag.current = { px: e.clientX, a: t0, b: t1, moved: false, id: e.pointerId }
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.px
    if (!d.moved && Math.abs(dx) < 4) return
    if (!d.moved) { d.moved = true; (e.currentTarget as HTMLElement).setPointerCapture(d.id) }
    const k = ((d.b - d.a) / plotW) * dx
    setRange([d.a - k, d.b - k])
  }
  const onPointerUp = () => { if (drag.current?.moved) suppress.current = true; drag.current = null }

  const onKey = (e: React.KeyboardEvent) => {
    const k = e.key.toLowerCase()
    if (k === 'w') zoomAt(0.75); else if (k === 's') zoomAt(1.33); else if (k === 'a') pan(-0.2); else if (k === 'd') pan(0.2); else return
    e.preventDefault()
  }

  return (
    <div className="tl" ref={rootRef} tabIndex={0} onKeyDown={onKey} aria-label="Timeline (W/S zoom, A/D pan)">
      <svg width={width} height={HEAD} style={{ display: 'block', flexShrink: 0, cursor: 'ew-resize' }}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
        <rect x={0} y={0} width={LABEL_W} height={HEAD} fill="var(--surface-soft)" />
        <rect x={LABEL_W} y={0} width={width - LABEL_W} height={HEAD} fill="#fff" />
        <line x1={0} y1={HEAD - 0.5} x2={width} y2={HEAD - 0.5} stroke="var(--line)" />
        <text x={10} y={22} fontSize={10.5} fill="var(--faint)" fontFamily="var(--mono)">{`${t0.toFixed(1)}–${t1.toFixed(1)} ms`}</text>
        <svg x={LABEL_W} y={0} width={plotW + 10} height={HEAD} overflow="hidden">
          <g transform={`translate(${-LABEL_W} 0)`}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={x(t)} y1={18} x2={x(t)} y2={HEAD} stroke="#B9B0A2" />
                <text x={x(t) + 3} y={28} fontSize={9.5} fill="var(--muted)" fontFamily="var(--mono)">{+t.toFixed(3)}ms</text>
              </g>
            ))}
            {flags.map(({ frame, t }) => (
              <g key={frame}>
                <path d={`M${x(t)} 2 h24 l-5 5 l5 5 h-24z`} fill={colorBy === 'frame' ? FRAME_COLORS[frame % FRAME_COLORS.length] : 'var(--primary)'} stroke={colorBy === 'frame' ? '#6B6558' : undefined} strokeWidth={0.6} />
                <text x={x(t) + 3} y={11} fontSize={9} fill={colorBy === 'frame' ? '#1F2430' : '#fff'} fontWeight={700}>f{frame}</text>
              </g>
            ))}
          </g>
        </svg>
      </svg>
      <div className="tl-body" ref={bodyRef}>
        <svg width={width} height={rows.height} role="img" aria-label="Timeline" style={{ display: 'block' }}
          onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
          onClickCapture={(e) => { if (suppress.current) { suppress.current = false; e.stopPropagation() } }}
          onClick={() => onSelect(null)}>
          <defs>
            <marker id="f-hi" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#174D47" /></marker>
            <marker id="f-lo" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="#9A9184" /></marker>
            <clipPath id="tl-plot"><rect x={LABEL_W} y={0} width={plotW + 10} height={rows.height} /></clipPath>
          </defs>
          <g clipPath="url(#tl-plot)">
            {ticks.map((t) => <line key={t} x1={x(t)} y1={0} x2={x(t)} y2={rows.height} stroke="#F4F0EA" />)}
            {flags.map(({ frame, t }) => <line key={frame} x1={x(t)} y1={0} x2={x(t)} y2={rows.height} stroke="var(--primary)" strokeDasharray="3 3" opacity={0.45} />)}
          </g>
          {rows.list.map((r) => r.kind === 'group' ? (
            <g key={r.id} style={{ cursor: 'pointer' }} onClick={(e) => { e.stopPropagation(); setCollapsed((c) => { const s = new Set(c); if (s.has(r.name)) s.delete(r.name); else s.add(r.name); return s }) }}>
              <rect x={0} y={r.y} width={width} height={ROW} fill="#F3EFE8" />
              <text x={8} y={r.y + 15} fontSize={11.5} fontWeight={700} fill="var(--text-2)">{collapsed.has(r.name) ? '▸' : '▾'} {r.name}</text>
            </g>
          ) : (
            <g key={r.id}>
              <rect x={0} y={r.y} width={LABEL_W} height={ROW} fill="var(--surface-soft)" />
              <text x={20} y={r.y + 15} fontSize={11} fill="#4A4F5A">{r.name}</text>
              <line x1={0} y1={r.y + ROW} x2={width} y2={r.y + ROW} stroke="#F1ECE4" />
            </g>
          ))}
          <line x1={LABEL_W} y1={0} x2={LABEL_W} y2={rows.height} stroke="var(--line)" />
          <g clipPath="url(#tl-plot)">
            {visible.map((s) => {
              const y = yOf.get(s.track)!
              const sx = x(s.start), w = Math.max(x(s.end) - sx, 1.5)
              const isSel = s.id === selectedSlice
              const hot = isSel || (highlightNode !== null && s.nodeId === highlightNode) || focus.has(s.id)
              const dimmed = (selectedSlice !== null || highlightNode !== null) && !hot
              return (
                <g key={s.id} style={{ cursor: 'pointer' }} opacity={dimmed ? 0.45 : 1} onClick={(e) => { e.stopPropagation(); onSelect(s) }}>
                  <rect x={sx} y={y + 3} width={w} height={ROW - 6} rx={2} fill={colorBy === 'frame' && s.frame !== null ? FRAME_COLORS[s.frame % FRAME_COLORS.length] : sliceColor(s.group)}
                    stroke={isSel ? '#174D47' : hot ? '#2F6F68' : 'rgba(0,0,0,0.08)'} strokeWidth={isSel ? 2.2 : hot ? 1.4 : 1} />
                  {w > 40 && <text x={Math.max(sx, LABEL_W) + 4} y={y + 15} fontSize={10} fill="#2B2F38" fontFamily="var(--mono)">{s.label}{s.frame !== null ? ` f${s.frame}` : ''}</text>}
                  <title>{`${s.label} · f${s.frame ?? '-'}\n${s.start.toFixed(3)} – ${s.end.toFixed(3)} ms (${(s.end - s.start).toFixed(3)} ms)`}</title>
                </g>
              )
            })}
            {showFlows && timeline.flows.map((f) => {
              const a = byId.get(f.from), b = byId.get(f.to)
              if (!a || !b || !yOf.has(a.track) || !yOf.has(b.track) || a.track === b.track) return null
              if ((a.end < t0 && b.start < t0) || (a.start > t1 && b.start > t1)) return null
              const hi = selectedSlice !== null && (f.from === selectedSlice || f.to === selectedSlice)
              const y1 = yOf.get(a.track)! + ROW / 2, y2 = yOf.get(b.track)! + ROW / 2
              // Streaming (OTF) successors start before the predecessor ends: anchor start-to-start.
              const x1 = b.start < a.end ? x(a.start) + 3 : x(a.end), x2 = x(b.start), dx = Math.max(14, Math.abs(x2 - x1) / 2)
              return <path key={`${f.from}>${f.to}`} d={`M${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`} fill="none" pointerEvents="none"
                stroke={hi ? '#174D47' : '#9A9184'} strokeWidth={hi ? 1.8 : 1} opacity={selectedSlice && !hi ? 0.25 : 0.85} markerEnd={`url(#${hi ? 'f-hi' : 'f-lo'})`} />
            })}
          </g>
        </svg>
      </div>
      <div className="tl-ctl">
        <button className="btn" onClick={() => zoomAt(0.75)} aria-label="확대" title="W / Ctrl+wheel">＋</button>
        <button className="btn" onClick={() => zoomAt(1.33)} aria-label="축소" title="S / Ctrl+wheel">－</button>
        <button className="btn" onClick={() => pan(-0.25)} title="A">◀</button>
        <button className="btn" onClick={() => pan(0.25)} title="D">▶</button>
        <button className="btn" onClick={() => setRange([timeline.start, timeline.end])}>전체</button>
        <button className="btn" onClick={() => setRange(defaultRange())}>100 ms</button>
        <span className="mono faint" style={{ fontSize: 11, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>drag·Shift+wheel 이동 · Ctrl+wheel/W·S 확대 · wheel 세로 스크롤</span>
      </div>
    </div>
  )
}
