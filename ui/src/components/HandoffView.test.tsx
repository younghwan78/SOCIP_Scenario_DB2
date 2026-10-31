// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { HandoffDoc } from '../lib/api'
import { HandoffView } from './HandoffView'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

const doc: HandoffDoc = {
  format: 'sdb.handoff/1',
  participants: [
    { id: 'app.game', layer: 'app', name: 'Game', detail: 'GameThread' },
    { id: 'hw.gpu', layer: 'hw', name: 'GPU' },
    { id: 'k.input', layer: 'kernel', name: 'input' },
  ],
  cadences: [
    { id: 'frame', name: 'Game frame', kind: 'frame', period_ms: 1000 / 60 },
    { id: 'touch', name: 'Touch report', kind: 'period', period_ms: 1000 / 240 },
    { id: 'hist', name: 'Histogram', kind: 'divided', of: 'frame', every: 10 },
  ],
  flows: [
    { id: 'game', name: 'Game frame', cadence: 'frame', summary: 'update → GPU', steps: [
      { to: 'app.game', call: 'update', task: 'game.update', slice: 'game.update#f3', node: 'cpu', t_ms: 0, dur_ms: 4 },
      { from: 'app.game', to: 'hw.gpu', call: 'render <b>pass</b>', task: 'gpu.render', slice: 'missing#f3', handoff: 'kick', t_ms: 4.5, dur_ms: 9 },
    ] },
    { id: 'touch', name: 'Touch input', cadence: 'touch', steps: [
      { to: 'k.input', call: 'touch IRQ', t_ms: 0, dur_ms: 0.05 },
      { from: 'k.input', to: 'app.game', call: 'onTouchEvent', cadence: 'frame', t_ms: 0.4, dur_ms: 0.2 },
    ] },
  ],
}

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLDivElement
afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null })

function render(flowId: string | null = null) {
  const onFlow = vi.fn(), onOpen = vi.fn()
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  act(() => root!.render(<HandoffView doc={doc} flowId={flowId} onFlow={onFlow} mode="layer" onMode={vi.fn()} source="test"
    canOpen={(id) => id === 'game.update#f3'} onOpen={onOpen} />))
  return { onFlow, onOpen }
}
const buttons = () => [...host.querySelectorAll('button')]
const button = (re: RegExp) => buttons().find((b) => re.test(b.textContent ?? ''))!
const textNode = (re: RegExp) => [...host.querySelectorAll('text')].find((t) => re.test(t.textContent ?? ''))!
const click = (el: Element) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })

describe('HandoffView', () => {
  it('defaults to all loops: each unit framed as its own loop, tagged frame-locked or independent', () => {
    render()
    expect(button(/^All loops$/).getAttribute('aria-selected')).toBe('true')
    const frames = [...host.querySelectorAll('text')].map((t) => t.textContent ?? '').filter((t) => t.startsWith('['))
    expect(frames).toEqual(expect.arrayContaining([expect.stringMatching(/^\[Game frame · 60 Hz\] frame loop/), expect.stringMatching(/^\[Touch input · 240 Hz\] independent loop/)]))
    expect(host.textContent).toContain('2 loops')
  })

  it('lists flows and every cadence with its rate; the layer header has one column per used layer', () => {
    render('game')
    expect(button(/^Game frame 60 Hz$/).getAttribute('aria-selected')).toBe('true')
    expect(button(/Touch report 240 Hz/).disabled).toBe(false)
    // a cadence no flow starts on (e.g. a 6 fps histogram scaler) is listed but not selectable
    expect(button(/Histogram 6 Hz/).disabled).toBe(true)
    expect(host.textContent).toContain('동시에')
    const head = host.querySelector('.handoff-head')!.textContent ?? ''
    expect(head).toContain('App')
    expect(head).toContain('HW')
  })

  it('renders step text as text (no markup injection) and opens only slices the trace has', () => {
    const { onOpen } = render()
    expect(textNode(/render <b>pass<\/b>/)).toBeTruthy()
    expect(host.querySelector('b b')).toBeNull()
    click(textNode(/^★ CPU update/))
    expect(onOpen).toHaveBeenCalledWith('game.update#f3')
    onOpen.mockClear()
    click(textNode(/render <b>pass<\/b>/))
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('cadence chips switch to the flow running at that rate; the cross-rate hand-off is listed', () => {
    const { onFlow } = render()
    click(button(/Touch report 240 Hz/))
    expect(onFlow).toHaveBeenCalledWith('touch')
    expect(host.querySelector('.handoff-links')!.textContent).toBe('Touch report · 240 Hz → Game frame · 60 Hz via onTouchEvent')
  })

  it('a step on another cadence carries a rate badge', () => {
    render('touch')
    expect(textNode(/^↻ Game frame · 60 Hz$/)).toBeTruthy()
  })
})
