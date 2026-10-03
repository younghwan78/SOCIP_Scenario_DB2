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

it('graph tooltip parks after a short rest: scrollable, full detail, Esc closes', async () => {
  const { vi } = await import('vitest')
  const { GraphView } = await import('../src/components/GraphView')
  vi.useFakeTimers()
  if (typeof ResizeObserver === 'undefined') Object.assign(globalThis, { ResizeObserver: class { observe() {} unobserve() {} disconnect() {} } })
  const layout = { nodes: [{ id: 'ip:sensor', label: 'Sensor', kind: 'ip', group: null, width: 120, height: 40, x: 10, y: 10 }], groups: [], edges: [], width: 300, height: 200 } as never
  const seen: boolean[] = []
  const tip = (id: string, pinned: boolean) => { seen.push(pinned); return <div className="body">{id}{pinned ? ' · modes: m0 m1 m2' : ''}</div> }
  const { host, unmount } = mount(<GraphView layout={layout} selected={null} related={new Set()} onSelect={() => {}} onToggleGroup={() => {}} tooltip={tip} />)
  const node = host.querySelector('g.node')!
  act(() => { node.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: 30, clientY: 30 })) })
  expect(host.querySelector('.gtip')?.className).not.toContain('pinned')
  act(() => { vi.advanceTimersByTime(450) })
  const tipEl = host.querySelector('.gtip.pinned')!
  expect(tipEl).not.toBeNull()
  expect(tipEl.textContent).toContain('modes')
  act(() => { node.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body })) })
  expect(host.querySelector('.gtip.pinned')).not.toBeNull()          // stays after leaving the node
  const wheel = new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: 40 })
  tipEl.dispatchEvent(wheel)
  expect(wheel.defaultPrevented).toBe(false)                          // native scroll inside the parked tooltip
  act(() => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })) })
  expect(host.querySelector('.gtip.pinned')).toBeNull()
  vi.useRealTimers()
  unmount()
})
