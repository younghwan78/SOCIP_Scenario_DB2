// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { RecomputePanel } from './RecomputePanel'
import { archApi, type BoardRow, type RecomputeResult } from '../lib/archExplore'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

it('admits one batch and stops queued writes when the project panel is removed', async () => {
  const host = document.createElement('div')
  const root = createRoot(host)
  let resolve!: (value: RecomputeResult) => void
  const call = vi.spyOn(archApi, 'recompute').mockImplementation(() => new Promise((r) => { resolve = r }))
  const props = { rows: [{ id: 'p1', variant_id: 'v1' }, { id: 'p2', variant_id: 'v2' }] as BoardRow[],
    staleIds: new Set<string>(), params: [], onDone: () => {}, onClose: () => {} }
  try {
    await act(async () => root.render(<RecomputePanel {...props} />))
    act(() => {
      const button = [...host.querySelectorAll('button')].find((b) => b.textContent === '2건 재계산')!
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(call).toHaveBeenCalledTimes(1)
    act(() => root.unmount())
    await act(async () => resolve({ prediction_id: 'p1', variant_id: 'v1', status: 'recomputed' }))
    expect(call).toHaveBeenCalledTimes(1)
  } finally { call.mockRestore() }
})
