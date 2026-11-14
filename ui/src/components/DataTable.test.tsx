// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { DataTable, type Column } from './DataTable'
import { cellText, filterRows, nodeText, presetHidden, toDelimited } from './tableTools'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
afterEach(() => { vi.restoreAllMocks(); localStorage.clear() })

interface Row { id: string; mw: number; note: string; ok: boolean }
const Bar = () => <i>bar</i>
const COLS: Column<Row>[] = [
  { key: 'id', label: 'Variant', sticky: true, sort: (r) => r.id, render: (r) => <span className="mono">{r.id}</span> },
  { key: 'mw', label: '추천 mW', sort: (r) => r.mw, render: (r) => <span><Bar /><b>{r.mw.toFixed(1)}</b></span> },
  { key: 'note', label: 'note', render: (r) => r.note },
  { key: 'ok', label: <span>판정</span>, exportLabel: '판정', text: (r) => (r.ok ? 'OK' : 'Fail'), render: (r) => <span className={r.ok ? 'ok' : 'bad'} /> },
]
const ROWS: Row[] = [
  { id: 'cam-a', mw: 120.25, note: 'has, comma', ok: true },
  { id: 'cam-b', mw: 80, note: 'say "hi"', ok: false },
  { id: 'yt-c', mw: 99.5, note: '', ok: true },
]

it('takes the literal text of a cell, skipping function components', () => {
  expect(nodeText(<span><Bar /><b>{'12.5'}</b> mW</span>)).toBe('12.5 mW')
  expect(nodeText([null, false, 'a', 3])).toBe('a 3')
  expect(cellText(COLS[3], ROWS[1])).toBe('Fail')
})

it('filters on every term (and), across the given columns', () => {
  expect(filterRows(ROWS, COLS, 'cam').map((r) => r.id)).toEqual(['cam-a', 'cam-b'])
  expect(filterRows(ROWS, COLS, 'cam fail').map((r) => r.id)).toEqual(['cam-b'])
  expect(filterRows(ROWS, COLS, '  ')).toBe(ROWS)
})

it('writes CSV with quoting and TSV without tabs or new lines in cells', () => {
  expect(toDelimited(ROWS.slice(0, 2), COLS, 'csv').split('\r\n')).toEqual([
    'Variant,추천 mW,note,판정', 'cam-a,120.3,"has, comma",OK', 'cam-b,80.0,"say ""hi""",Fail'])
  expect(toDelimited([{ ...ROWS[0], note: 'a\tb\nc' }], COLS, 'tsv').split('\n')[1]).toBe('cam-a\t120.3\ta b c\tOK')
})

it('a preset hides every other column except the sticky one', () => {
  expect(presetHidden(COLS, { id: 'p', label: 'P', keys: ['mw'] })).toEqual(['note', 'ok'])
})

it('the table tools filter rows, hide columns and copy what is shown', async () => {
  const writeText = vi.fn(() => Promise.resolve())
  Object.assign(navigator, { clipboard: { writeText } })
  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  await act(async () => root.render(<DataTable id="t" columns={COLS} rows={ROWS} rowKey={(r) => r.id} defaultSort={{ key: 'mw', dir: -1 }}
    tools={{ presets: [{ id: 'power', label: 'Power', keys: ['mw'] }] }} />))
  const ids = () => [...host.querySelectorAll('tbody tr')].map((tr) => tr.querySelector('td')?.textContent)
  expect(ids()).toEqual(['cam-a', 'yt-c', 'cam-b'])
  const input = host.querySelector<HTMLInputElement>('.dt-filter')!
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => { set.call(input, 'cam'); input.dispatchEvent(new Event('input', { bubbles: true })) })
  expect(ids()).toEqual(['cam-a', 'cam-b'])
  expect(host.querySelector('.dt-count')?.textContent).toBe('2 / 3행')
  const power = [...host.querySelectorAll<HTMLButtonElement>('.dt-presets button')].find((b) => b.textContent === 'Power')!
  await act(async () => power.click())
  expect([...host.querySelectorAll('thead th')].map((th) => th.textContent?.replace(/[▲▼↕]/g, ''))).toEqual(['Variant', '추천 mW'])
  expect(power.getAttribute('aria-pressed')).toBe('true')
  const copy = [...host.querySelectorAll<HTMLButtonElement>('.dt-tools button')].find((b) => b.textContent === '복사')!
  await act(async () => copy.click())
  expect(writeText).toHaveBeenCalledWith('Variant\t추천 mW\ncam-a\t120.3\ncam-b\t80.0')
  act(() => root.unmount())
  host.remove()
})
