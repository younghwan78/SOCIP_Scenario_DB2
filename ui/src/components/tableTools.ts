import { isValidElement, type ReactNode } from 'react'

/** U-09: the shared table tools (quick filter, column choice, copy / CSV) work on cell text.
 * A column can give it (`text`); otherwise it is the text inside the rendered cell. Function components
 * (bars, badges with their own logic) are not called, so only literal text in the cell counts. */
export function nodeText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number' || typeof node === 'bigint') return String(node)
  if (Array.isArray(node)) return node.map(nodeText).filter(Boolean).join(' ').replace(/\s+/g, ' ').trim()
  if (isValidElement(node)) {
    if (typeof node.type !== 'string' && typeof node.type !== 'symbol') return ''
    return nodeText((node.props as { children?: ReactNode }).children)
  }
  return ''
}

export interface TextColumn<T> { key: string; label: ReactNode; exportLabel?: string; text?: (row: T) => string; render: (row: T) => ReactNode }

export const cellText = <T,>(c: TextColumn<T>, row: T): string => (c.text ? c.text(row) : nodeText(c.render(row))).trim()
export const headText = <T,>(c: TextColumn<T>): string => c.exportLabel ?? (nodeText(c.label) || c.key)

/** Every whitespace-separated term must appear in some cell (case-insensitive). */
export function filterRows<T>(rows: T[], columns: TextColumn<T>[], query: string): T[] {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return rows
  return rows.filter((r) => {
    const hay = columns.map((c) => cellText(c, r).toLowerCase()).join('\u0001')
    return terms.every((t) => hay.includes(t))
  })
}

const csvCell = (s: string) => (/[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s)
const tsvCell = (s: string) => s.replace(/[\t\r\n]+/g, ' ')

export function toDelimited<T>(rows: T[], columns: TextColumn<T>[], kind: 'csv' | 'tsv'): string {
  const cell = kind === 'csv' ? csvCell : tsvCell
  const sep = kind === 'csv' ? ',' : '\t'
  const lines = [columns.map((c) => cell(headText(c))).join(sep), ...rows.map((r) => columns.map((c) => cell(cellText(c, r))).join(sep))]
  return lines.join(kind === 'csv' ? '\r\n' : '\n')
}

export function downloadText(name: string, text: string, type = 'text/csv') {
  // BOM so spreadsheet apps read the Korean labels as UTF-8
  const blob = new Blob(['﻿', text], { type: `${type};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = name
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

export interface ColumnPreset { id: string; label: string; keys: string[] }

/** The hidden set a preset gives: every column not in the preset, except the ones that are always shown. */
export function presetHidden(all: { key: string; sticky?: boolean }[], preset: ColumnPreset): string[] {
  return all.filter((c) => !c.sticky && !preset.keys.includes(c.key)).map((c) => c.key)
}
