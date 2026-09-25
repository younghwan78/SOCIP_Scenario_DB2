// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { IpTopology } from '../src/components/IpInternalView'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

it('exposes the full IP name and lets keyboard users select a node', () => {
  const ip = { pid: 'cpu', viewId: 'pipeline:cpu', label: 'CPU task with a long name',
    type: 'sw', lane: 'sw', ipRef: '', rdma: { used: 0 }, wdma: { used: 0 } }
  const model = { ips: [ip], links: [], byPid: new Map([['cpu', ip]]) }
  const host = document.createElement('div'), root = createRoot(host), select = vi.fn()
  try {
    act(() => root.render(<IpTopology model={model as never} selectedPid={null} onSelect={select} colorBy="vdd" />))
    expect(host.querySelector('svg')?.getAttribute('role')).toBe('group')
    const button = host.querySelector('[role="button"]')!
    expect(button.getAttribute('aria-label')).toBe(ip.label)
    act(() => { button.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })) })
    expect(select).toHaveBeenCalledWith('pipeline:cpu')
  } finally { act(() => root.unmount()) }
})
