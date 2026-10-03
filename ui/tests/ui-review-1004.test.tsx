// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { DataTable, type Column } from '../src/components/DataTable'
import { CompareSummary, type ItemInfo, type MetricRow } from '../src/components/CompareSummary'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

function mount(node: React.ReactNode) {
  const host = document.createElement('div'), root = createRoot(host)
  act(() => root.render(node))
  return { host, unmount: () => act(() => root.unmount()) }
}

it('keeps the sticky reference row first and sticky under any sort', () => {
  type R = { id: string; v: number }
  const rows: R[] = [{ id: 'a', v: 3 }, { id: 'ref', v: 9 }, { id: 'c', v: 1 }]
  const cols: Column<R>[] = [{ key: 'id', label: 'id', render: (r) => r.id }, { key: 'v', label: 'v', sort: (r) => r.v, render: (r) => r.v }]
  localStorage.clear()
  const { host, unmount } = mount(<DataTable id="t1004" columns={cols} rows={rows} rowKey={(r) => r.id} stickyTop={(r) => r.id === 'ref'} />)
  const ids = () => [...host.querySelectorAll('tbody tr')].map((tr) => tr.querySelector('td')!.textContent)
  expect(ids()).toEqual(['ref', 'a', 'c'])
  act(() => (host.querySelectorAll('th')[1] as HTMLElement).click())   // sort v ascending
  expect(ids()).toEqual(['ref', 'c', 'a'])
  act(() => (host.querySelectorAll('th')[1] as HTMLElement).click())   // descending
  expect(ids()).toEqual(['ref', 'a', 'c'])
  expect(host.querySelector('tbody tr')!.className).toContain('pin-sticky')
  expect((host.querySelector('table') as HTMLTableElement).style.getPropertyValue('--dt-head-h')).not.toBe('')
  unmount()
})

it('wraps the compare summary table in a scroller and compacts 4+ items', () => {
  const items: ItemInfo[] = ['ref', 'b', 'c', 'd'].map((label, i) => ({ label: `${label}-very-long-variant-id-uhd60-hdr10-eis`, color: '#000', source: 'sim', full: label + i }))
  const metrics: MetricRow[] = [{ group: 'Power', key: 'total_power_mw', label: 'Total', unit: 'mW', values: [100, 90, 120, 100.2] }]
  const { host, unmount } = mount(<CompareSummary items={items} metrics={metrics} />)
  expect(host.querySelector('.cs')!.className).toContain('cs-compact')
  expect(host.querySelector('.cs-table-wrap > table.cs-table')).not.toBeNull()
  expect(host.querySelectorAll('th .cs-th-l')).toHaveLength(4)
  unmount()
})
