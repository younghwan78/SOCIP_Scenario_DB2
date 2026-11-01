// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import { TimingInputsHelp, type TimingInputs } from './TimingInputsHelp'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
const host = document.createElement('div')
document.body.appendChild(host)
let root = createRoot(host)
afterEach(() => { act(() => root.unmount()); root = createRoot(host) })

const inputs: TimingInputs = { statistic: 'mean', throughput: 'pipelined', margin: 0.25, profile: undefined, measured: null, powerParams: '', defaultPowerParams: null }
const press = async (el: Element) => {
  await act(async () => { el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })) })
  await act(async () => { (el as HTMLElement).click() })
}
const open = () => document.querySelector('[role="dialog"][aria-label="입력 영향"]')

it('opens and closes from the "?" trigger, and closes on an outside click', async () => {
  await act(async () => root.render(<TimingInputsHelp inputs={inputs} />))
  const btn = host.querySelector('button[aria-label="입력 영향"]')!
  await press(btn)
  expect(open()).not.toBeNull()
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })   // outside-click listener is armed after a tick
  await press(btn)
  expect(open()).toBeNull()                                                 // the trigger toggles, it does not reopen
  await press(btn)
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  await press(document.body)
  expect(open()).toBeNull()
})
