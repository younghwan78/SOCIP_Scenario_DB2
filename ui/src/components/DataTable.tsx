import { Fragment, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { usePref } from './Layout'
import { downloadText, filterRows, presetHidden, toDelimited, type ColumnPreset } from './tableTools'

// ---------------------------------------------------------------------------
// DataTable: sortable (click header: ▲ → ▼ → off) and resizable columns
// (drag header edge, double-click = default). Widths + sort persist per table id.
// `tools` (U-09) adds the shared quick filter, column choice (+ presets) and copy / CSV.
// ---------------------------------------------------------------------------

export type SortValue = string | number | null | undefined

export interface Column<T> {
  key: string
  label: ReactNode
  /** default width px */
  width?: number
  minWidth?: number
  align?: 'left' | 'right' | 'center'
  /** value used for sorting; omit → column not sortable */
  sort?: (row: T) => SortValue
  /** first click direction (-1 = descending first, e.g. Load / numbers) */
  firstDir?: 1 | -1
  render: (row: T) => ReactNode
  cellClass?: (row: T) => string
  title?: (row: T) => string | undefined
  headTitle?: string
  headClass?: string
  /** sticky first column (always shown, also with tools) */
  sticky?: boolean
  /** cell text for the quick filter and copy / CSV; default: the text inside the rendered cell */
  text?: (row: T) => string
  /** header text in copy / CSV when the label is not plain text */
  exportLabel?: string
}

export interface TableTools {
  /** column bundles, e.g. Power / Timing / 검증 */
  presets?: ColumnPreset[]
  /** CSV file name without extension (default: the table id) */
  filename?: string
}

export interface RowGroup<T> {
  id: string
  header: ReactNode
  rows: T[]
  open?: boolean
  onToggle?: () => void
  className?: string
}

interface Props<T> {
  id: string
  columns: Column<T>[]
  rows?: T[]
  groups?: RowGroup<T>[]
  rowKey: (row: T) => string
  rowClass?: (row: T) => string
  onRowClick?: (row: T) => void
  /** rows kept on top while no explicit sort is active */
  pinTop?: (row: T) => boolean
  /** rows always first (whatever the sort) and sticky under the header (e.g. the ★ reference variant) */
  stickyTop?: (row: T) => boolean
  defaultSort?: { key: string; dir: 1 | -1 }
  className?: string
  empty?: ReactNode
  /** Bound mounted data rows. Sticky reference rows remain visible on every page. */
  pageSize?: number
  /** U-09 shared tools: quick filter, column choice, copy / CSV */
  tools?: boolean | TableTools
}

export function compareValues(a: SortValue, b: SortValue): number {
  const na = a === null || a === undefined || a === '' || a === '—'
  const nb = b === null || b === undefined || b === '' || b === '—'
  if (na || nb) return na === nb ? 0 : na ? 1 : -1 // blanks always last
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
}

export function sortRows<T>(rows: T[], get: ((r: T) => SortValue) | undefined, dir: 1 | -1, pinTop?: (r: T) => boolean): T[] {
  if (!get) return pinTop ? [...rows.filter(pinTop), ...rows.filter((r) => !pinTop(r))] : rows
  const idx = rows.map((r, i) => ({ r, i, v: get(r) }))
  idx.sort((x, y) => {
    if (pinTop) { const px = pinTop(x.r), py = pinTop(y.r); if (px !== py) return px ? -1 : 1 }
    const c = compareValues(x.v, y.v)
    // blanks last in both directions
    const blankX = x.v === null || x.v === undefined || x.v === '' || x.v === '—'
    const blankY = y.v === null || y.v === undefined || y.v === '' || y.v === '—'
    if (blankX || blankY) return c || x.i - y.i
    return c * dir || x.i - y.i
  })
  return idx.map((x) => x.r)
}

export function DataTable<T>({ id, columns: allColumns, rows: allRows, groups: allGroups, rowKey, rowClass, onRowClick, pinTop, stickyTop, defaultSort, className = '', empty, pageSize = 100, tools }: Props<T>) {
  const toolOpts: TableTools | null = tools ? (tools === true ? {} : tools) : null
  const [hidden, setHidden] = usePref<string[]>(`table.${id}.hidden`, [])
  const [query, setQuery] = useState('')
  const [copied, setCopied] = useState(false)
  const columns = toolOpts ? allColumns.filter((c) => c.sticky || !hidden.includes(c.key)) : allColumns
  const q = toolOpts ? query : ''
  // the reference rows (stickyTop) stay whatever the filter
  const keepOrMatch = (list: T[]) => {
    if (!q.trim()) return list
    const hit = new Set(filterRows(list, columns, q))
    return list.filter((r) => hit.has(r) || !!stickyTop?.(r))
  }
  const rows = useMemo(() => (allRows ? keepOrMatch(allRows) : allRows), [allRows, q, columns.length, hidden]) // eslint-disable-line react-hooks/exhaustive-deps
  const groups = allGroups && q.trim() ? allGroups.map((g) => ({ ...g, rows: keepOrMatch(g.rows) })).filter((g) => g.rows.length) : allGroups
  const [widths, setWidths] = usePref<Record<string, number>>(`table.${id}.w`, {})
  const [sort, setSort] = usePref<{ key: string; dir: 1 | -1 } | null>(`table.${id}.sort`, defaultSort ?? null)
  const drag = useRef<{ key: string; x: number; w: number } | null>(null)
  const [page, setPage] = useState(0)
  const widthOf = (c: Column<T>) => Math.max(c.minWidth ?? 48, widths[c.key] ?? c.width ?? 140)
  const total = columns.reduce((s, c) => s + widthOf(c), 0)
  const sortCol = allColumns.find((c) => c.key === sort?.key && c.sort) // a hidden column keeps its sort
  // pinned rows (reference) only while no explicit sort is active
  const order = (list: T[]) => {
    const sorted = sortRows(stickyTop ? list.filter((r) => !stickyTop(r)) : list, sortCol?.sort, sort?.dir ?? 1, sortCol ? undefined : pinTop)
    return stickyTop ? [...list.filter(stickyTop), ...sorted] : sorted
  }
  const sortedRows = useMemo(() => (rows ? order(rows) : []), [rows, sortCol, sort?.dir, stickyTop, pinTop]) // eslint-disable-line react-hooks/exhaustive-deps
  // header height → CSS var so sticky rows sit right under the (possibly two-line) header
  const tableRef = useRef<HTMLTableElement>(null)
  useLayoutEffect(() => {
    const t = tableRef.current, head = t?.tHead
    if (!t || !head || !stickyTop) return
    const set = () => t.style.setProperty('--dt-head-h', `${head.getBoundingClientRect().height || 33}px`)
    set()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(set); ro.observe(head)
    return () => ro.disconnect()
  }, [stickyTop])

  const onHead = (c: Column<T>) => {
    if (!c.sort) return
    setPage(0)
    const first = c.firstDir ?? 1
    setSort((s) => (s?.key !== c.key ? { key: c.key, dir: first } : s.dir === first ? { key: c.key, dir: (-first) as 1 | -1 } : null))
  }
  const startResize = (e: React.PointerEvent, c: Column<T>) => {
    e.preventDefault(); e.stopPropagation()
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    drag.current = { key: c.key, x: e.clientX, w: widthOf(c) }
    document.body.classList.add('resizing-x')
  }
  const moveResize = (e: React.PointerEvent, c: Column<T>) => {
    const d = drag.current
    if (!d || d.key !== c.key) return
    const w = Math.round(Math.min(900, Math.max(c.minWidth ?? 48, d.w + e.clientX - d.x)))
    setWidths((p) => ({ ...p, [c.key]: w }))
  }
  const endResize = () => { drag.current = null; document.body.classList.remove('resizing-x') }

  const seenKeys = new Map<string, number>()
  const renderRow = (r: T) => {
    const k0 = rowKey(r)
    const dup = seenKeys.get(k0) ?? 0
    seenKeys.set(k0, dup + 1)
    const k = dup ? `${k0}#${dup}` : k0
    return (
      <tr key={k} className={`${rowClass?.(r) ?? ''} ${onRowClick ? 'clickable' : ''} ${stickyTop?.(r) ? 'pin-sticky' : ''}`} onClick={onRowClick ? () => onRowClick(r) : undefined}
        tabIndex={onRowClick ? 0 : undefined} aria-label={onRowClick ? `${rowKey(r)} 상세` : undefined}
        onKeyDown={onRowClick ? (e) => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onRowClick(r) } } : undefined}>
        {columns.map((c) => (
          <td key={c.key} className={`${c.cellClass?.(r) ?? ''} ${c.sticky ? 'rowhead' : ''}`} style={c.align ? { textAlign: c.align } : undefined} title={c.title?.(r)}>
            {c.render(r)}
          </td>
        ))}
      </tr>
    )
  }

  const count = groups ? groups.reduce((s, g) => s + g.rows.length, 0) : sortedRows.length
  const pinned = !groups && stickyTop ? sortedRows.filter(stickyTop) : []
  const orderedGroups = groups?.map((g) => ({ ...g, ordered: g.open === false ? [] : order(g.rows) }))
  const pageable = orderedGroups ? orderedGroups.flatMap((g) => g.ordered) : sortedRows.filter((r) => !stickyTop?.(r))
  const limit = Math.max(1, Math.floor(pageSize))
  const pages = Math.max(1, Math.ceil(pageable.length / limit))
  const currentPage = Math.min(page, pages - 1)
  const visible = pageable.slice(currentPage * limit, (currentPage + 1) * limit)
  let groupOffset = 0
  const visibleGroups = orderedGroups?.map((g) => {
    const start = groupOffset; groupOffset += g.ordered.length
    return { ...g, visible: g.ordered.slice(Math.max(0, currentPage * limit - start), Math.max(0, (currentPage + 1) * limit - start)) }
  }).filter((g) => g.open === false || g.visible.length)
  const totalRows = allGroups ? allGroups.reduce((s, g) => s + g.rows.length, 0) : (allRows?.length ?? 0)
  // copy / CSV: every filtered row in the shown order (all pages, closed groups included), shown columns
  const exportRows = () => (groups ? groups.flatMap((g) => order(g.rows)) : sortedRows)
  const copy = () => {
    const text = toDelimited(exportRows(), columns, 'tsv')
    try { void navigator.clipboard?.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) }) } catch { /* clipboard unavailable */ }
  }
  const activePreset = toolOpts?.presets?.find((p) => { const h = presetHidden(allColumns, p); return h.length === hidden.length && h.every((k) => hidden.includes(k)) })
  const hideable = allColumns.filter((c) => !c.sticky)
  return (
    <>
      {toolOpts && <div className="dt-tools" role="toolbar" aria-label={`${id} 표 도구`}>
        <input type="search" className="dt-filter" value={query} placeholder="표 안에서 찾기" aria-label="표 안에서 찾기 (공백 = 그리고)"
          onChange={(e) => { setQuery(e.target.value); setPage(0) }} />
        <span className="faint dt-count" aria-live="polite">{q.trim() ? `${count} / ${totalRows}행` : `${totalRows}행`}</span>
        {toolOpts.presets && toolOpts.presets.length > 0 && <span className="seg dt-presets" role="group" aria-label="열 묶음">
          <button type="button" className={hidden.length === 0 ? 'on' : ''} aria-pressed={hidden.length === 0} onClick={() => setHidden([])}>전체</button>
          {toolOpts.presets.map((p) => <button key={p.id} type="button" className={activePreset?.id === p.id ? 'on' : ''} aria-pressed={activePreset?.id === p.id}
            onClick={() => setHidden(presetHidden(allColumns, p))}>{p.label}</button>)}
        </span>}
        <details className="dt-cols">
          <summary>열 {columns.length} / {allColumns.length}</summary>
          <div className="dt-cols-menu">
            {hideable.map((c) => <label key={c.key}><input type="checkbox" checked={!hidden.includes(c.key)}
              onChange={(e) => setHidden((h) => (e.target.checked ? h.filter((k) => k !== c.key) : [...h, c.key]))} /> {c.exportLabel ?? (typeof c.label === 'string' && c.label ? c.label : c.key)}</label>)}
            <button type="button" className="link-btn" onClick={() => setHidden([])}>모두 보기</button>
          </div>
        </details>
        <button type="button" className="btn tb-mini" onClick={copy} title="보이는 열 · 필터된 모든 행을 표 형식(TSV)으로 복사">{copied ? '복사됨' : '복사'}</button>
        <button type="button" className="btn tb-mini" onClick={() => downloadText(`${toolOpts.filename ?? id}.csv`, toDelimited(exportRows(), columns, 'csv'))}
          title="보이는 열 · 필터된 모든 행을 CSV로 저장">CSV</button>
      </div>}
      <table ref={tableRef} className={`grid dt ${className}`} style={{ width: total, minWidth: '100%' }}>
        <colgroup>{columns.map((c) => <col key={c.key} style={{ width: widthOf(c) }} />)}</colgroup>
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sortCol?.key === c.key
              return (
                <th key={c.key} className={`${c.sort ? 'sortable' : ''} ${active ? 'sorted' : ''} ${c.sticky ? 'rowhead' : ''} ${c.headClass ?? ''}`}
                  style={c.align ? { textAlign: c.align } : undefined} onClick={() => onHead(c)} title={c.headTitle ?? (c.sort ? (c.firstDir === -1 ? '클릭: 내림 → 오름 → 해제' : '클릭: 오름 → 내림 → 해제') : undefined)}
                  aria-sort={active ? (sort!.dir === 1 ? 'ascending' : 'descending') : undefined}>
                  {c.sort ? <button type="button" className="dt-sort th-in" onClick={(e) => { e.stopPropagation(); onHead(c) }}>
                    <span className="th-label">{c.label}</span>
                    <span className="sort-ind" aria-hidden="true">{active ? (sort!.dir === 1 ? '▲' : '▼') : '↕'}</span>
                  </button> : <span className="th-in"><span className="th-label">{c.label}</span></span>}
                  <span className="col-resizer" role="separator" aria-label={`${typeof c.label === 'string' ? c.label || '열' : '열'} 폭 조절`} tabIndex={0} aria-orientation="vertical" aria-valuemin={c.minWidth ?? 48} aria-valuemax={900} aria-valuenow={widthOf(c)} aria-valuetext={`${widthOf(c)}px`} title="좌우 방향키: 폭 조절 · Home/더블클릭: 기본값"
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => {
                      if (!['ArrowLeft', 'ArrowRight', 'Home'].includes(e.key)) return
                      e.preventDefault(); e.stopPropagation()
                      setWidths((p) => { const n = { ...p }; if (e.key === 'Home') delete n[c.key]
                        else n[c.key] = Math.max(c.minWidth ?? 48, Math.min(900, widthOf(c) + (e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 48 : 16)))
                        return n })
                    }}
                    onPointerDown={(e) => startResize(e, c)} onPointerMove={(e) => moveResize(e, c)} onPointerUp={endResize} onPointerCancel={endResize}
                    onDoubleClick={(e) => { e.stopPropagation(); setWidths((p) => { const n = { ...p }; delete n[c.key]; return n }) }} />
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {visibleGroups ? visibleGroups.map((g) => (
            <Fragment key={`g:${g.id}`}>
              <tr className={`group-row ${g.className ?? ''}`} onClick={g.onToggle} tabIndex={g.onToggle ? 0 : undefined} aria-expanded={g.onToggle ? g.open !== false : undefined}
                onKeyDown={g.onToggle ? (e) => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); g.onToggle?.() } } : undefined}>
                <td colSpan={columns.length}>{g.header}</td>
              </tr>
              {g.visible.map(renderRow)}
            </Fragment>
          )) : [...pinned, ...visible].map(renderRow)}
        </tbody>
      </table>
      {pages > 1 && <nav className="dt-pages" aria-label={`${id} 표 페이지`}>
        <button type="button" className="btn tb-mini" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>이전</button>
        <span aria-live="polite">{currentPage + 1} / {pages} · {pageable.length}행{pinned.length ? ` · 기준 ${pinned.length}행 고정` : ''}</span>
        <button type="button" className="btn tb-mini" disabled={currentPage + 1 >= pages} onClick={() => setPage(currentPage + 1)}>다음</button>
      </nav>}
      {count === 0 && empty}
    </>
  )
}
