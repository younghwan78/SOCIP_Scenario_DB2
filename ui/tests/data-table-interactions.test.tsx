// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { DataTable } from '../src/components/DataTable'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
const host = document.createElement('div')
let root = createRoot(host)
afterEach(() => { act(() => root.unmount()); root = createRoot(host); localStorage.clear() })
const cols = [{ key: 'n', label: '값', width: 120, sort: (r: number) => r, render: (r: number) => r }]

it('bounds mounted rows and keeps a baseline visible across pages', () => {
  const rows = Array.from({ length: 205 }, (_, i) => i)
  act(() => root.render(<DataTable id="bounded" columns={cols} rows={rows} rowKey={String} stickyTop={(r) => r === 0} />))
  expect(host.querySelectorAll('tbody tr')).toHaveLength(101)
  const next = [...host.querySelectorAll('button')].find((b) => b.textContent === '다음')!
  act(() => next.click())
  expect(host.querySelector('tbody tr')?.textContent).toBe('0')
  expect(host.querySelectorAll('tbody tr')[1].textContent).toBe('101')
  act(() => next.click())
  expect(host.querySelectorAll('tbody tr')).toHaveLength(5)
})

it('supports keyboard row selection, sorting buttons, and column resize', () => {
  const pick = vi.fn()
  act(() => root.render(<DataTable id="keyboard" columns={cols} rows={[2, 1]} rowKey={String} onRowClick={pick} />))
  const row = host.querySelector('tbody tr')!
  act(() => row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
  expect(pick).toHaveBeenCalledWith(2)
  const sort = host.querySelector<HTMLButtonElement>('th button')!
  expect(sort.type).toBe('button')
  act(() => sort.click())
  expect(host.querySelector('tbody tr')?.textContent).toBe('1')
  expect(host.querySelector('th')?.getAttribute('aria-sort')).toBe('ascending')
  const handle = host.querySelector('[role="separator"]')!
  act(() => handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })))
  expect(handle.getAttribute('aria-valuenow')).toBe('136')
  act(() => handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true })))
  expect(handle.getAttribute('aria-valuenow')).toBe('120')
})

it('paginates grouped rows by position even when two groups share the same row objects', () => {
  const rows = Array.from({ length: 60 }, (_, i) => i)
  act(() => root.render(<DataTable id="grouped" columns={cols} groups={[{ id: 'a', header: 'A', rows }, { id: 'b', header: 'B', rows }]} rowKey={String} />))
  expect(host.querySelectorAll('tbody tr:not(.group-row)')).toHaveLength(100)
})
