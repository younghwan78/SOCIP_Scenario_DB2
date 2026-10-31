// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { TimelineEvent } from '../lib/api'
import { buildTimeline, FULLSTACK_GROUPS } from '../lib/timeline'
import { TimelineView, type FlowMode } from './TimelineView'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
beforeAll(() => {
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
})

const e = (task_id: string, group: string, start: number, end: number, preds: string[] = [], handoff?: string): TimelineEvent => ({
  task_id, logical_task_id: task_id.split('#')[0], layer: group.toLowerCase(), start_ms: start, end_ms: end, frame_index: 0,
  resource_name: `fullstack/${group}/${task_id.split('#')[0]} · t`, predecessors: preds, handoff,
})
// a -> b -> c is one chain, a -> x is a sibling branch of b
const tl = buildTimeline([
  e('a#f0', 'HAL', 0, 1), e('b#f0', 'KERNEL', 2, 3, ['a#f0'], 'kick'), e('c#f0', 'HW', 4, 9, ['b#f0'], 'irq'), e('x#f0', 'APP', 2, 4, ['a#f0'], 'ipc'),
], { maxFrames: 8, groupOrder: FULLSTACK_GROUPS })

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLDivElement
afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null })

function render(flowMode: FlowMode, selected: string | null, onSelect = vi.fn()) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  act(() => root!.render(<TimelineView timeline={tl} selectedSlice={selected} highlightNode={null} showFlows flowMode={flowMode} onSelect={onSelect} autoFocus labelWidth={200} />))
  return { onSelect, el: host.querySelector('.tl') as HTMLElement, flows: () => host.querySelectorAll('path[marker-end]') }
}
const press = (el: HTMLElement, key: string) => act(() => { el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })) })

describe('TimelineView full-stack options', () => {
  it('chain mode draws only the selection chain, colored by hand-off kind', () => {
    const { flows } = render('chain', 'c#f0')
    expect(flows().length).toBe(2)   // a->b, b->c ; a->x is a sibling branch
    expect([...flows()].map((p) => p.getAttribute('stroke'))).toEqual(expect.arrayContaining(['#2563EB', '#B45309']))
  })

  it('chain mode draws nothing until a slice is selected; neighbours mode keeps every flow', () => {
    expect(render('chain', null).flows().length).toBe(0)
    act(() => root?.unmount()); host.remove()
    expect(render('neighbours', null).flows().length).toBe(3)
  })

  it('takes focus on mount; Esc clears the selection and F fits the chain', () => {
    const { el, onSelect } = render('chain', 'c#f0')
    expect(document.activeElement).toBe(el)
    const range = () => host.querySelector('svg text')?.textContent
    const before = range()
    press(el, 'f')
    expect(range()).not.toBe(before)
    expect(range()).toMatch(/^-?0\.\d–\d+\.\d ms$/)
    press(el, 'Escape')
    expect(onSelect).toHaveBeenCalledWith(null)
  })
})
