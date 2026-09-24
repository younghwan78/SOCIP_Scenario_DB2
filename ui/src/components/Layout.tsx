import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

// ---------------------------------------------------------------------------
// Persisted UI prefs (per viewer; storage may be disabled → in-memory fallback)
// ---------------------------------------------------------------------------

export function loadPref<T>(key: string, fallback: T): T {
  try { const v = localStorage.getItem(key); return v === null ? fallback : (JSON.parse(v) as T) } catch { return fallback }
}
export function savePref(key: string, v: unknown): void {
  try { localStorage.setItem(key, JSON.stringify(v)) } catch { /* storage disabled */ }
}

/** useState that persists to localStorage under `sdb.<key>`. */
export function usePref<T>(key: string, fallback: T): [T, (v: T | ((p: T) => T)) => void] {
  const k = `sdb.${key}`
  const [v, setV] = useState<T>(() => loadPref(k, fallback))
  const set = useCallback((next: T | ((p: T) => T)) => setV((p) => {
    const n = typeof next === 'function' ? (next as (p: T) => T)(p) : next
    savePref(k, n)
    return n
  }), [k])
  return [v, set]
}

// ---------------------------------------------------------------------------
// Resizer: drag handle between two regions (axis x = vertical bar, y = horizontal bar)
// ---------------------------------------------------------------------------

interface ResizerProps {
  axis: 'x' | 'y'
  /** Called on every move with the pointer delta (px) since drag start, plus the size at drag start. */
  onResize: (delta: number) => void
  onStart?: () => void
  onReset?: () => void
  label: string
  className?: string
}

export function Resizer({ axis, onResize, onStart, onReset, label, className = '' }: ResizerProps) {
  const start = useRef<number | null>(null)
  return (
    <div className={`resizer resizer-${axis} ${className}`} role="separator" aria-orientation={axis === 'x' ? 'vertical' : 'horizontal'} aria-label={label} tabIndex={0}
      title={`${label} · drag로 조절 · 더블클릭 = 기본값`}
      onPointerDown={(e) => {
        if (e.button !== 0) return
        e.preventDefault()
        e.currentTarget.setPointerCapture(e.pointerId)
        start.current = axis === 'x' ? e.clientX : e.clientY
        onStart?.()
        document.body.classList.add(axis === 'x' ? 'resizing-x' : 'resizing-y')
      }}
      onPointerMove={(e) => { if (start.current !== null) onResize((axis === 'x' ? e.clientX : e.clientY) - start.current) }}
      onPointerUp={() => { start.current = null; document.body.classList.remove('resizing-x', 'resizing-y') }}
      onPointerCancel={() => { start.current = null; document.body.classList.remove('resizing-x', 'resizing-y') }}
      onDoubleClick={onReset}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 48 : 16
        const dec = axis === 'x' ? 'ArrowLeft' : 'ArrowUp', inc = axis === 'x' ? 'ArrowRight' : 'ArrowDown'
        if (e.key !== dec && e.key !== inc) return
        e.preventDefault(); onStart?.(); onResize(e.key === inc ? step : -step)
      }} />
  )
}

/** Size state + drag helpers for a Resizer, clamped and persisted. `sign` = -1 when the region grows opposite to the pointer (bottom panel). */
export function useResizable(key: string, fallback: number, min: number, max: number, sign: 1 | -1 = 1) {
  const [size, setSize] = usePref<number>(key, fallback)
  const base = useRef(size)
  const clampSize = (v: number) => Math.round(Math.min(max, Math.max(min, v)))
  return {
    size: clampSize(size),
    set: (v: number) => setSize(clampSize(v)),
    reset: () => setSize(fallback),
    bind: { onStart: () => { base.current = clampSize(size) }, onResize: (d: number) => setSize(clampSize(base.current + sign * d)) },
  }
}

// ---------------------------------------------------------------------------
// PageLayout: top (filters/toolbar) · main · bottom (details panel)
// ---------------------------------------------------------------------------

export interface BottomTab { id: string; label: ReactNode; content: ReactNode }

interface PageLayoutProps {
  id: string                 // pref namespace (per page)
  top?: ReactNode
  main: ReactNode
  bottomTabs?: BottomTab[]
  bottomDefault?: number
  /** Controlled active tab (e.g. jump to "DMA" when a row is needed). */
  activeTab?: string
  onTabChange?: (id: string) => void
}

/**
 * Page skeleton used by every page:
 *  ┌ top  (toolbar / filters) — collapsible, height resizable (auto by default)
 *  ├ main (fills the rest, owns its own scrolling)
 *  └ bottom (tabbed details) — collapsible (Ctrl+J), height resizable
 */
export function PageLayout({ id, top, main, bottomTabs, bottomDefault = 260, activeTab, onTabChange }: PageLayoutProps) {
  const [topOpen, setTopOpen] = usePref(`${id}.top.open`, true)
  const [topH, setTopH] = usePref<number | null>(`${id}.top.h`, null)
  const topRef = useRef<HTMLDivElement>(null)
  const topBase = useRef(0)
  const bottom = useResizable(`${id}.bottom.h`, bottomDefault, 120, 900, -1)
  const [bottomOpen, setBottomOpen] = usePref(`${id}.bottom.open`, true)
  const [tabState, setTabState] = usePref<string>(`${id}.bottom.tab`, bottomTabs?.[0]?.id ?? '')
  const tab = activeTab ?? tabState
  const setTab = (t: string) => { setTabState(t); onTabChange?.(t) }
  const current = bottomTabs?.find((t) => t.id === tab) ?? bottomTabs?.[0]

  useEffect(() => {
    if (!bottomTabs?.length) return
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'j') { e.preventDefault(); setBottomOpen((o) => !o) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [bottomTabs?.length, setBottomOpen])

  return (
    <div className="pl">
      {top && <>
        <div className={`pl-top ${topOpen ? '' : 'closed'}`} ref={topRef} style={topOpen && topH !== null ? { height: topH } : undefined}>
          {topOpen ? top : <span className="faint" style={{ fontSize: 12 }}>도구 모음 접힘</span>}
        </div>
        <div className="pl-top-bar">
          <Resizer axis="y" label="상단 영역 높이"
            onStart={() => { topBase.current = topRef.current?.getBoundingClientRect().height ?? 0; if (!topOpen) setTopOpen(true) }}
            onResize={(d) => setTopH(Math.round(Math.min(400, Math.max(32, topBase.current + d))))}
            onReset={() => setTopH(null)} />
          <button className="pl-toggle" onClick={() => setTopOpen((o) => !o)} title={topOpen ? '상단 접기' : '상단 펼치기'} aria-label={topOpen ? '상단 접기' : '상단 펼치기'}>{topOpen ? '▴' : '▾'}</button>
        </div>
      </>}
      <div className="pl-main">{main}</div>
      {bottomTabs && bottomTabs.length > 0 && <>
        {bottomOpen && <Resizer axis="y" label="하단 패널 높이" {...bottom.bind} onReset={bottom.reset} />}
        <section className="pl-bottom" style={{ height: bottomOpen ? bottom.size : undefined }}>
          <div className="pl-tabs" role="tablist">
            {bottomTabs.map((t) => (
              <button key={t.id} role="tab" aria-selected={bottomOpen && current?.id === t.id} className={bottomOpen && current?.id === t.id ? 'on' : ''}
                onClick={() => { setTab(t.id); setBottomOpen(true) }}>{t.label}</button>
            ))}
            <span className="grow" />
            <span className="faint" style={{ fontSize: 11 }}>Ctrl+J</span>
            <button className="pl-toggle" onClick={() => setBottomOpen((o) => !o)} aria-label={bottomOpen ? '하단 패널 접기' : '하단 패널 펼치기'} title={bottomOpen ? '접기' : '펼치기'}>{bottomOpen ? '▾' : '▴'}</button>
          </div>
          {bottomOpen && <div className="pl-bottom-body">{current?.content}</div>}
        </section>
      </>}
    </div>
  )
}
