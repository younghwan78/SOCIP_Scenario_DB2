import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { edgePath, type Layout, type Placed } from '../lib/graph'

const EDGE_STYLE = {
  OTF: { stroke: 'var(--otf)', dash: undefined, marker: 'm-otf', width: 1.8 },
  M2M: { stroke: 'var(--m2m)', dash: '6 4', marker: 'm-m2m', width: 1.8 },
  control: { stroke: 'var(--control)', dash: '2 3', marker: 'm-ctl', width: 1.3 },
} as const

const BAND_TONE = ['#F8D9BF', '#F3E3B3', '#F4C7A6', '#E2D6EE', '#CFE5DF', '#E5E1DA']
const MIN_SCALE = 0.25
const MAX_SCALE = 3
const PAD = 16

interface Props {
  layout: Layout
  selected: string | null
  related: ReadonlySet<string>
  onSelect: (id: string | null) => void
  onToggleGroup: (groupId: string) => void
  showOps: boolean
  /** rich hover card for a node id (replaces the native SVG title) */
  tooltip?: (id: string) => ReactNode
}

/** Small numbered circles: RDMA (blue) / WDMA (orange) channels in use; hollow when the IP has none in use. */
function DmaBadges({ n }: { n: Placed }) {
  const items = [n.wdma && { k: 'W', v: n.wdma, c: '#F97316' }, n.rdma && { k: 'R', v: n.rdma, c: '#2563EB' }].filter(Boolean) as { k: string; v: { used: number; total: number | null }; c: string }[]
  return <>{items.map((b, i) => {
    const cx = n.x + n.width - 6 - i * 15, cy = n.y + 1
    return <g key={b.k} pointerEvents="none">
      <circle cx={cx} cy={cy} r={6.5} fill={b.v.used ? b.c : '#fff'} stroke={b.c} strokeWidth={1.2} />
      <text x={cx} y={cy + 3} textAnchor="middle" fontSize={b.v.used > 9 ? 7.5 : 8.5} fontWeight={700} fill={b.v.used ? '#fff' : b.c} fontFamily="var(--mono)">{b.v.used}</text>
    </g>
  })}</>
}

interface View { x: number; y: number; s: number }

function opsText(n: Placed): string {
  const ops = (n.data?.active_operations ?? {}) as Record<string, unknown>
  const out: string[] = []
  if (ops.scale) out.push(typeof ops.scale_ratio === 'number' ? `scale ×${ops.scale_ratio.toFixed(2)}` : 'scale')
  if (ops.crop) out.push('crop')
  if (ops.rotate) out.push(`rot ${ops.rotate}°`)
  if (ops.colorspace_convert) out.push('CSC')
  if (ops.compose) out.push('compose')
  return out.join(' · ')
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** Fit modes: 'all' = whole graph, 'width' = fill width and align to top (default, readable). */
export function fitView(layout: Layout, w: number, h: number, mode: 'all' | 'width'): View {
  const sw = (w - PAD * 2) / Math.max(layout.width, 1)
  const sh = (h - PAD * 2) / Math.max(layout.height, 1)
  // 'width' keeps labels readable (≥ 75%); when the graph is still wider, centre on the source (sensor).
  const s = clamp(mode === 'all' ? Math.min(sw, sh, 1.2) : Math.min(Math.max(sw, 0.75), 1.2), MIN_SCALE, MAX_SCALE)
  const vw = w / s
  const src = layout.nodes.find((n) => n.kind === 'external')
  const x = layout.width * s <= w ? (layout.width - vw) / 2 : src ? clamp(src.x + src.width / 2 - vw / 2, -PAD / s, layout.width - vw + PAD / s) : -PAD / s
  const y = mode === 'all' && layout.height * s < h ? (layout.height - h / s) / 2 : -PAD / s
  return { x, y, s }
}

/**
 * SVG pipeline canvas with viewport pan/zoom (Figma-style):
 * wheel / trackpad = scroll, Ctrl(⌘)+wheel or pinch = zoom at cursor, drag = pan, double-click = fit.
 */
export function GraphView({ layout, selected, related, onSelect, onToggleGroup, showOps, tooltip }: Props) {
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 600, h: 400 })
  const [view, setView] = useState<View>({ x: 0, y: 0, s: 1 })
  const viewRef = useRef(view)
  viewRef.current = view
  const env = useRef({ size, layout })
  env.current = { size, layout }
  // Keep at least ~25% of the graph on screen whatever the pan/zoom.
  const update = useCallback((fn: (v: View) => View) => setView((prev) => {
    const v = fn(prev)
    const { size: sz, layout: l } = env.current
    const vw = sz.w / v.s, vh = sz.h / v.s
    const mx = Math.min(vw, l.width) * 0.25, my = Math.min(vh, l.height) * 0.25
    return { s: v.s, x: clamp(v.x, mx - vw - PAD, l.width - mx + PAD), y: clamp(v.y, my - vh - PAD, l.height - my + PAD) }
  }), [])
  const drag = useRef<{ px: number; py: number; x: number; y: number; moved: boolean; id: number } | null>(null)
  const suppressClick = useRef(false)
  const fitted = useRef<Layout | null>(null)

  useLayoutEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setSize({ w: Math.max(200, e.contentRect.width), h: Math.max(200, e.contentRect.height) }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const touched = useRef(false)
  const fit = useCallback((mode: 'all' | 'width') => { touched.current = false; update(() => fitView(layout, size.w, size.h, mode)) }, [layout, size, update])
  // Re-fit when a new layout arrives (lens / group / variant change), keep the user's view on resize.
  useEffect(() => {
    if (fitted.current !== layout) { fitted.current = layout; fit('width') }
    else if (!touched.current) fit('width') // panel resized before any manual pan/zoom → keep fitted
  }, [layout, fit])

  const zoomAt = useCallback((factor: number, cx?: number, cy?: number) => {
    touched.current = true
    update((v) => {
      const s = clamp(v.s * factor, MIN_SCALE, MAX_SCALE)
      const px = cx ?? size.w / 2, py = cy ?? size.h / 2
      return { s, x: v.x + px / v.s - px / s, y: v.y + py / v.s - py / s }
    })
  }, [size, update])

  // Native (non-passive) wheel listener so preventDefault stops page scroll / browser zoom.
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      touched.current = true
      const r = el.getBoundingClientRect()
      if (e.ctrlKey || e.metaKey) {
        zoomAt(Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0022)), e.clientX - r.left, e.clientY - r.top)
      } else {
        const k = e.deltaMode === 1 ? 16 : 1
        const dx = (e.shiftKey ? e.deltaY : e.deltaX) * k, dy = e.shiftKey ? 0 : e.deltaY * k
        update((v) => ({ ...v, x: v.x + dx / v.s, y: v.y + dy / v.s }))
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomAt])

  // Bring an externally selected node (timing slice / DMA row) into view.
  useEffect(() => {
    if (!selected) return
    const n = layout.nodes.find((x) => x.id === selected)
    if (!n) return
    const v = viewRef.current
    const vw = size.w / v.s, vh = size.h / v.s
    const inside = n.x >= v.x && n.x + n.width <= v.x + vw && n.y >= v.y && n.y + n.height <= v.y + vh
    if (!inside) update(() => ({ ...v, x: n.x + n.width / 2 - vw / 2, y: n.y + n.height / 2 - vh / 2 }))
  }, [selected, layout, size, update])

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return
    drag.current = { px: e.clientX, py: e.clientY, x: view.x, y: view.y, moved: false, id: e.pointerId }
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.px, dy = e.clientY - d.py
    if (!d.moved && Math.hypot(dx, dy) < 4) return
    if (!d.moved) { d.moved = true; touched.current = true; wrapRef.current?.setPointerCapture(d.id) }
    update((v) => ({ ...v, x: d.x - dx / v.s, y: d.y - dy / v.s }))
  }
  const onPointerUp = () => {
    if (drag.current?.moved) suppressClick.current = true
    drag.current = null
  }

  const dim = selected !== null
  const edges = useMemo(() => [...layout.edges].sort((a, b) => Number(related.has(a.source) && related.has(a.target)) - Number(related.has(b.source) && related.has(b.target))), [layout.edges, related])
  const vb = `${view.x} ${view.y} ${size.w / view.s} ${size.h / view.s}`

  return (
    <div className="graph-canvas" ref={wrapRef} title="wheel 스크롤 · Ctrl+wheel 확대 · drag 이동 · 빈 곳 더블클릭 = 전체" data-dragging={drag.current?.moved ? '1' : undefined}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
      onClickCapture={(e) => { if (suppressClick.current) { suppressClick.current = false; e.stopPropagation(); e.preventDefault() } }}
      onDoubleClick={(e) => { if ((e.target as Element).tagName === 'svg') fit('all') }}>
      <svg width={size.w} height={size.h} viewBox={vb} role="img" aria-label="Pipeline graph" onClick={() => onSelect(null)} style={{ display: 'block' }}>
        <defs>
          {(['otf', 'm2m', 'ctl'] as const).map((k) => (
            <marker key={k} id={`m-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M0 0L10 5L0 10z" fill={k === 'otf' ? '#2563EB' : k === 'm2m' ? '#F97316' : '#A16207'} />
            </marker>
          ))}
        </defs>
        {layout.lanes?.map((l, i) => (
          <g key={`lane:${l.id}`}>
            <rect x={0} y={l.y} width={layout.width} height={l.height} fill={i % 2 ? 'rgba(243,239,232,.55)' : 'rgba(255,255,255,.7)'} />
            <line x1={0} y1={l.y + l.height} x2={layout.width} y2={l.y + l.height} stroke="#E8E1D6" />
            <text x={10} y={l.y + l.height / 2 + 4} fontSize={11} fontWeight={700} fill="var(--muted)">{l.label}</text>
          </g>
        ))}
        {layout.bands?.map((b, i) => (
          <g key={`band:${i}`}>
            <rect x={b.x} y={layout.headerH ?? 0} width={b.width - 8} height={layout.height - (layout.headerH ?? 0) - 8} fill={BAND_TONE[b.tone % BAND_TONE.length]} opacity={0.22} rx={6} />
            <rect x={b.x} y={4} width={b.width - 8} height={(layout.headerH ?? 40) - 10} rx={6} fill={BAND_TONE[b.tone % BAND_TONE.length]} opacity={0.9} />
            <text x={b.x + 8} y={19} fontSize={b.width < 150 ? 10 : 11} fontWeight={700} fill="#2B2F38">{b.width < 120 ? b.label.replace(' · sensor V-sync (OTF)', ' (OTF)').replace(' hand-off', '') : b.label}</text>
            {b.sub && <text x={b.x + 8} y={32} fontSize={9.5} fill="#4A4F5A" fontFamily="var(--mono)">{b.sub}</text>}
          </g>
        ))}
        {layout.groups.map((g) => (
          <rect key={g.id} x={g.x} y={g.y} width={g.width} height={g.height} rx={8} fill="rgba(255,255,255,0.65)" stroke={g.id === 'g:sw' ? '#D6C49A' : '#E6D3BC'} />
        ))}
        {edges.map((e) => {
          const st = EDGE_STYLE[e.kind]
          const on = !dim || (related.has(e.source) && related.has(e.target))
          return <path key={e.id} d={edgePath(e.points)} fill="none" stroke={st.stroke} strokeWidth={on && dim ? st.width + 0.8 : st.width}
            strokeDasharray={st.dash} markerEnd={`url(#${st.marker})`} opacity={on ? (e.faint && !(dim && on) ? 0.4 : 1) : 0.18}><title>{e.ports || e.kind}</title></path>
        })}
        {edges.filter((e) => e.label && e.points.length > 1).map((e) => {
          const p = e.points[Math.floor(e.points.length / 2)], q = e.points[Math.floor(e.points.length / 2) - 1] ?? p
          return <text key={`l:${e.id}`} x={(p.x + q.x) / 2 + 3} y={(p.y + q.y) / 2 - 3} fontSize={9} fontWeight={700} fill="var(--m2m)" style={{ paintOrder: 'stroke' }} stroke="#fff" strokeWidth={3}>{e.label}</text>
        })}
        {layout.nodes.map((n) => {
          const on = !dim || related.has(n.id)
          const isSel = selected === n.id
          const common = { opacity: on ? 1 : 0.3, className: 'node', onClick: (ev: React.MouseEvent) => { ev.stopPropagation(); if (n.kind === 'group') onToggleGroup(n.id); else onSelect(n.id) },
            onMouseMove: tooltip && n.kind !== 'group' ? (ev: React.MouseEvent) => { const r = wrapRef.current!.getBoundingClientRect(); setHover({ id: n.id, x: ev.clientX - r.left, y: ev.clientY - r.top }) } : undefined,
            onMouseLeave: tooltip ? () => setHover(null) : undefined }
          if (n.kind === 'buffer') {
            return (
              <g key={n.id} {...common}>
                <rect x={n.x} y={n.y} width={n.width} height={n.height} rx={5} fill={n.tone === 'stat' ? '#FFF7E6' : n.tone === 'history' ? '#EEF2FF' : n.tone === 'optional' ? '#F4F4F5' : 'var(--buf-fill)'}
                  stroke={isSel ? 'var(--primary-strong)' : n.tone === 'stat' ? '#B45309' : n.tone === 'history' ? '#4F46E5' : n.tone === 'optional' ? '#A1A1AA' : 'var(--buf-line)'} strokeWidth={isSel ? 2.4 : 1.1}
                  strokeDasharray={n.tone === 'stat' || n.tone === 'optional' ? '4 3' : undefined} />
                <text x={n.x + 6} y={n.y + 12} fontSize={10} fontWeight={700} fill="var(--buf-text)" fontFamily="var(--mono)">{n.label}</text>
                <text x={n.x + 6} y={n.y + 24} fontSize={9} fill="var(--buf-text)" fontFamily="var(--mono)">{n.sub}</text>
                {n.sub2 && <text x={n.x + 6} y={n.y + 35} fontSize={9} fill="var(--buf-text)" fontFamily="var(--mono)" opacity={0.8}>{n.sub2}</text>}
                {!tooltip && <title>{`${n.bufferRef}\n${n.sub ?? ''}\n${n.sub2 ?? ''}`}</title>}
              </g>
            )
          }
          const style = n.kind === 'external' ? { fill: 'var(--ext-fill)', stroke: 'var(--ext-line)', text: '#1E293B', rx: 16 }
            : n.kind === 'sw' ? { fill: '#FFFFFF', stroke: 'var(--control)', text: '#1F2937', rx: 13 }
              : n.kind === 'group' ? { fill: '#FFF8F0', stroke: '#E6D3BC', text: '#9A4A12', rx: 8 }
                : { fill: 'var(--ip-fill)', stroke: 'var(--ip-line)', text: 'var(--ip-text)', rx: 6 }
          const ops = showOps && n.kind === 'ip' ? opsText(n) : ''
          return (
            <g key={n.id} {...common}>
              <rect x={n.x} y={n.y} width={n.width} height={n.height} rx={style.rx} fill={style.fill}
                stroke={isSel ? 'var(--primary-strong)' : style.stroke} strokeWidth={isSel ? 2.6 : n.kind === 'external' ? 1.6 : 1.2} strokeDasharray={n.kind === 'group' ? '4 3' : undefined} />
              {n.kind === 'external' && <rect x={n.x + 4} y={n.y + 4} width={n.width - 8} height={n.height - 8} rx={12} fill="none" stroke="var(--ext-line)" strokeWidth={0.8} strokeDasharray="2 2" />}
              {n.sub && n.height >= 32 ? <>
                <text x={n.x + n.width / 2} y={n.y + 13} textAnchor="middle" fontSize={n.kind === 'sw' ? 10.5 : 11} fontWeight={600} fill={style.text}>{n.label}</text>
                <text x={n.x + n.width / 2} y={n.y + 24} textAnchor="middle" fontSize={9} fill={style.text} fontFamily="var(--mono)" opacity={0.85}>{n.sub}</text>
                {n.sub2 && <text x={n.x + n.width / 2} y={n.y + 33.5} textAnchor="middle" fontSize={8.5} fill={style.text} fontFamily="var(--mono)" opacity={0.65}>{n.sub2}</text>}
              </> : <text x={n.x + n.width / 2} y={n.y + n.height / 2 + 4} textAnchor="middle" fontSize={n.kind === 'sw' ? 10.5 : 11.5} fontWeight={600} fill={style.text}>{n.label}</text>}
              {n.kind === 'external' && <text x={n.x + n.width - 4} y={n.y - 3} textAnchor="end" fontSize={8.5} fontWeight={700} fill="var(--ext-line)">EXT</text>}
              {ops && <text x={n.x + n.width / 2} y={n.y + n.height + 11} textAnchor="middle" fontSize={9.5} fill="#9A4A12">{ops}</text>}
              <DmaBadges n={n} />
              {!tooltip && <title>{[n.data?.ip_ref ?? n.label, n.sub, n.sub2].filter(Boolean).join('\n')}</title>}
            </g>
          )
        })}
        {layout.groups.map((g) => (
          <text key={`t:${g.id}`} x={g.x + 10} y={g.y + 16} fontSize={10.5} fontWeight={700} fill={g.id === 'g:sw' ? '#8A5A0B' : '#9A4A12'} style={{ cursor: 'pointer', paintOrder: 'stroke' }}
            stroke="#FFFFFF" strokeWidth={3} onClick={(e) => { e.stopPropagation(); onToggleGroup(g.id) }}>▾ {g.label} · {g.count}</text>
        ))}
      </svg>
      {tooltip && hover && !drag.current?.moved && (() => {
        const body = tooltip(hover.id)
        if (!body) return null
        const left = hover.x + 16 + 340 > size.w ? Math.max(4, hover.x - 356) : hover.x + 16
        const top = Math.min(hover.y + 12, Math.max(4, size.h - 40))
        return <div className="gtip" style={{ left, top, maxHeight: size.h - top - 8 }}>{body}</div>
      })()}
      <div className="canvas-ctl" onPointerDown={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
        <button className="btn" onClick={() => zoomAt(1 / 1.25)} aria-label="축소" title="축소 (Ctrl+wheel)">－</button>
        <button className="btn mono" onClick={() => zoomAt(1 / view.s)} title="100%로">{Math.round(view.s * 100)}%</button>
        <button className="btn" onClick={() => zoomAt(1.25)} aria-label="확대" title="확대 (Ctrl+wheel)">＋</button>
        <button className="btn" onClick={() => fit('width')} title="폭 맞춤">폭</button>
        <button className="btn" onClick={() => fit('all')} title="전체 보기 (빈 곳 더블클릭)">전체</button>
      </div>
    </div>
  )
}
