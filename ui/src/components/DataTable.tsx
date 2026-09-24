import { Fragment, useMemo, useRef, type ReactNode } from 'react'
import { usePref } from './Layout'

// ---------------------------------------------------------------------------
// DataTable: sortable (click header: ▲ → ▼ → off) and resizable columns
// (drag header edge, double-click = default). Widths + sort persist per table id.
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
  render: (row: T) => ReactNode
  cellClass?: (row: T) => string
  title?: (row: T) => string | undefined
  headTitle?: string
  headClass?: string
  /** sticky first column */
  sticky?: boolean
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
  /** rows kept on top regardless of sort (e.g. reference variant) */
  pinTop?: (row: T) => boolean
  defaultSort?: { key: string; dir: 1 | -1 }
  className?: string
  empty?: ReactNode
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

export function DataTable<T>({ id, columns, rows, groups, rowKey, rowClass, onRowClick, pinTop, defaultSort, className = '', empty }: Props<T>) {
  const [widths, setWidths] = usePref<Record<string, number>>(`table.${id}.w`, {})
  const [sort, setSort] = usePref<{ key: string; dir: 1 | -1 } | null>(`table.${id}.sort`, defaultSort ?? null)
  const drag = useRef<{ key: string; x: number; w: number } | null>(null)
  const widthOf = (c: Column<T>) => Math.max(c.minWidth ?? 48, widths[c.key] ?? c.width ?? 140)
  const total = columns.reduce((s, c) => s + widthOf(c), 0)
  const sortCol = columns.find((c) => c.key === sort?.key && c.sort)
  const order = (list: T[]) => sortRows(list, sortCol?.sort, sort?.dir ?? 1, pinTop)
  const sortedRows = useMemo(() => (rows ? order(rows) : []), [rows, sortCol, sort?.dir]) // eslint-disable-line react-hooks/exhaustive-deps

  const onHead = (c: Column<T>) => {
    if (!c.sort) return
    setSort((s) => (s?.key !== c.key ? { key: c.key, dir: 1 } : s.dir === 1 ? { key: c.key, dir: -1 } : null))
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
      <tr key={k} className={`${rowClass?.(r) ?? ''} ${onRowClick ? 'clickable' : ''}`} onClick={onRowClick ? () => onRowClick(r) : undefined}>
        {columns.map((c) => (
          <td key={c.key} className={`${c.cellClass?.(r) ?? ''} ${c.sticky ? 'rowhead' : ''}`} style={c.align ? { textAlign: c.align } : undefined} title={c.title?.(r)}>
            {c.render(r)}
          </td>
        ))}
      </tr>
    )
  }

  const count = groups ? groups.reduce((s, g) => s + g.rows.length, 0) : sortedRows.length
  return (
    <>
      <table className={`grid dt ${className}`} style={{ width: total, minWidth: '100%' }}>
        <colgroup>{columns.map((c) => <col key={c.key} style={{ width: widthOf(c) }} />)}</colgroup>
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sortCol?.key === c.key
              return (
                <th key={c.key} className={`${c.sort ? 'sortable' : ''} ${active ? 'sorted' : ''} ${c.sticky ? 'rowhead' : ''} ${c.headClass ?? ''}`}
                  style={c.align ? { textAlign: c.align } : undefined} onClick={() => onHead(c)} title={c.headTitle ?? (c.sort ? '클릭: 오름 → 내림 → 해제' : undefined)}
                  aria-sort={active ? (sort!.dir === 1 ? 'ascending' : 'descending') : undefined}>
                  <span className="th-in">
                    <span className="th-label">{c.label}</span>
                    {c.sort && <span className="sort-ind" aria-hidden="true">{active ? (sort!.dir === 1 ? '▲' : '▼') : '↕'}</span>}
                  </span>
                  <span className="col-resizer" role="separator" aria-label="열 폭 조절" title="drag: 폭 조절 · 더블클릭: 기본값"
                    onClick={(e) => e.stopPropagation()}
                    onPointerDown={(e) => startResize(e, c)} onPointerMove={(e) => moveResize(e, c)} onPointerUp={endResize} onPointerCancel={endResize}
                    onDoubleClick={(e) => { e.stopPropagation(); setWidths((p) => { const n = { ...p }; delete n[c.key]; return n }) }} />
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {groups ? groups.map((g) => (
            <Fragment key={`g:${g.id}`}>
              <tr className={`group-row ${g.className ?? ''}`} onClick={g.onToggle}>
                <td colSpan={columns.length}>{g.header}</td>
              </tr>
              {g.open !== false && order(g.rows).map(renderRow)}
            </Fragment>
          )) : sortedRows.map(renderRow)}
        </tbody>
      </table>
      {count === 0 && empty}
    </>
  )
}
