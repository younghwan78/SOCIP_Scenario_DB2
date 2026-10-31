// Column policy (G-07 / M4): a column whose every shown row is empty, or has one same value, carries no
// comparison signal. Such columns are hidden by default and listed in a "숨김 n" toggle with their value.
import type { Column, SortValue } from '../components/DataTable'

export interface IdleColumn { key: string; label: string; kind: 'empty' | 'constant'; value: string | null }

const text = (v: SortValue): string | null => (v === null || v === undefined || v === '' || v === '—' ? null : String(v))

/** Columns among ``keys`` (value = the column's sort accessor) that are empty or constant over ``rows``. */
export function idleColumns<T>(columns: Column<T>[], rows: T[], keys: string[], labelOf: (c: Column<T>) => string): IdleColumn[] {
  if (!rows.length) return []
  const out: IdleColumn[] = []
  for (const c of columns) {
    if (!keys.includes(c.key) || !c.sort) continue
    const values = new Set(rows.map((r) => text(c.sort!(r))))
    if (values.size === 1 && values.has(null)) out.push({ key: c.key, label: labelOf(c), kind: 'empty', value: null })
    else if (values.size === 1 && rows.length > 1) out.push({ key: c.key, label: labelOf(c), kind: 'constant', value: [...values][0] })
  }
  return out
}
