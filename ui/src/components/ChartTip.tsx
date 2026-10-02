// Rich hover tooltip shared by every SVG chart (replaces native <title> text).
// Content is structured: colored header, one headline value (e.g. mean), then key/value rows
// grouped into sections, with tone (good/bad) for deltas and a muted foot note.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export interface TipRow { k: string; v: string; tone?: 'good' | 'bad' | 'muted' | 'strong'; color?: string }
export interface TipContent {
  title: ReactNode
  color?: string
  /** headline (e.g. "평균 33.34 ms") shown large right under the title */
  head?: { label: string; value: string; tone?: TipRow['tone'] }
  rows?: (TipRow | { section: string })[]
  foot?: string
}

type Show = (e: { clientX: number; clientY: number }, c: TipContent) => void
const Ctx = createContext<{ show: Show; hide: () => void } | null>(null)

export function ChartTipProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<{ x: number; y: number; c: TipContent } | null>(null)
  const show = useCallback<Show>((e, c) => setTip({ x: e.clientX, y: e.clientY, c }), [])
  const hide = useCallback(() => setTip(null), [])
  return <Ctx.Provider value={{ show, hide }}>{children}{tip && <TipBox {...tip} />}</Ctx.Provider>
}

function TipBox({ x, y, c }: { x: number; y: number; c: TipContent }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ left: x + 14, top: y + 14 })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const w = el.offsetWidth, h = el.offsetHeight
    const left = x + 14 + w > window.innerWidth - 8 ? Math.max(8, x - w - 14) : x + 14
    const top = y + 14 + h > window.innerHeight - 8 ? Math.max(8, y - h - 14) : y + 14
    setPos({ left, top })
  }, [x, y, c])
  return createPortal(
    <div ref={ref} className="ctip" role="tooltip" style={{ left: pos.left, top: pos.top, borderTopColor: c.color ?? 'var(--primary)' }}>
      <div className="ctip-t">{c.color && <span className="ctip-sw" style={{ background: c.color }} />}{c.title}</div>
      {c.head && <div className="ctip-h"><span>{c.head.label}</span><b className={`mono ${c.head.tone ? `t-${c.head.tone}` : ''}`}>{c.head.value}</b></div>}
      {c.rows && c.rows.length > 0 && <div className="ctip-rows">
        {c.rows.map((r, i) => 'section' in r
          ? <div key={i} className="ctip-sec">{r.section}</div>
          : <div key={i} className="ctip-row"><span>{r.color && <span className="ctip-sw" style={{ background: r.color }} />}{r.k}</span><span className={`mono ${r.tone ? `t-${r.tone}` : ''}`}>{r.v}</span></div>)}
      </div>}
      {c.foot && <div className="ctip-f">{c.foot}</div>}
    </div>, document.body)
}

/** Props to spread on an SVG/HTML element: hover shows the tooltip, leave hides it. */
export function useTip(): (c: TipContent | (() => TipContent)) => { onMouseMove: (e: React.MouseEvent) => void; onMouseLeave: () => void } {
  const ctx = useContext(Ctx)
  return useCallback((c) => ({
    onMouseMove: (e: React.MouseEvent) => ctx?.show(e, typeof c === 'function' ? c() : c),
    onMouseLeave: () => ctx?.hide(),
  }), [ctx])
}

/** Signed delta text with tone: lowerIsBetter decides which direction is "good". */
export function deltaRow(k: string, v: number, ref: number, unit: string, digits = 1, lowerIsBetter = true): TipRow {
  const d = v - ref
  const pct = ref ? (d / ref) * 100 : null
  const tone: TipRow['tone'] = Math.abs(d) < 1e-9 ? 'muted' : (d < 0) === lowerIsBetter ? 'good' : 'bad'
  return { k, v: `${d >= 0 ? '+' : ''}${d.toFixed(digits)} ${unit}${pct !== null ? ` (${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%)` : ''}`, tone }
}
