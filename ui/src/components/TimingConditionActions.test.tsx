// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { ConditionBar } from './TimingWorkbench'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

it('admits only one save and never shows a previous condition save on a new condition', async () => {
  const host = document.createElement('div')
  const root = createRoot(host)
  let resolve!: (value: string) => void
  const save = vi.fn(() => new Promise<string>((r) => { resolve = r }))
  const cond = { statistic: 'max', scale: 1, eis: 'auto', cpuModel: 'flat', throughput: 'stage', margin: 0.25, profile: null, overrides: {} }
  const props = { cond, verdict: 'ok', onSaveEvidence: save, onRegister: async () => '', onOpenPredictions: () => {} }
  try {
    await act(async () => root.render(<ConditionBar key="old" {...props} />))
    act(() => {
      const button = host.querySelector('button')!
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(save).toHaveBeenCalledTimes(1)
    await act(async () => root.render(<ConditionBar key="new" {...props} cond={{ ...cond, scale: 1.2 }} />))
    await act(async () => resolve('saved previous condition'))
    expect(host.textContent).not.toContain('saved previous condition')
    expect(host.textContent).toContain('×1.2')
  } finally { act(() => root.unmount()) }
})
