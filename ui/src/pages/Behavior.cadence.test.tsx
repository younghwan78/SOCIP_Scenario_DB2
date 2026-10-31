// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { HandoffDoc, TimelineEvent } from '../lib/api'
import { buildTimeline, FULLSTACK_GROUPS } from '../lib/timeline'
import { CadenceTab, cadenceRows } from './Behavior'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

const ev = (id: string, layer: string, group: string, s: number, e: number, extra: Partial<TimelineEvent> = {}): TimelineEvent => ({
  task_id: id, logical_task_id: id.split('#')[0], layer, start_ms: s, end_ms: e, resource_name: `fullstack/${group}/p · ${id.split('#')[0]}`, ...extra })
const tl = buildTimeline([
  ev('abox.dsp#c0', 'hw', 'HW', 3, 3.8, { frame_index: null, cadence_period_ms: 20, node_id: 'abox' }),
  ev('aud.read#c0', 'hal', 'HAL', 4, 4.2, { frame_index: null, cadence_period_ms: 20, predecessors: ['abox.dsp#c0'] }),
  ev('abox.dsp#c1', 'hw', 'HW', 23, 23.8, { frame_index: null, cadence_period_ms: 20, node_id: 'abox' }),
  ev('aud.read#c1', 'hal', 'HAL', 24, 24.2, { frame_index: null, cadence_period_ms: 20, predecessors: ['abox.dsp#c1'] }),
], { maxFrames: 8, groupOrder: FULLSTACK_GROUPS })
const doc: HandoffDoc = { format: 'sdb.handoff/1', participants: [{ id: 'hw', layer: 'hw', name: 'ABOX' }, { id: 'hal', layer: 'hal', name: 'audio HAL' }],
  cadences: [{ id: 'abox', name: 'ABOX period', kind: 'period', period_ms: 20 }],
  flows: [{ id: 'audio', name: 'Audio period', cadence: 'abox', steps: [{ to: 'hw', task: 'abox.dsp' }, { from: 'hw', to: 'hal', task: 'aud.read' }] }] }

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLDivElement
afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null })

describe('Cadence tab', () => {
  it('a row opens a summary popover: rate and its basis, execution, links, and jumps to the other tabs', () => {
    const onOpenSlice = vi.fn(), onOpenFlow = vi.fn()
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    act(() => root!.render(<CadenceTab timeline={tl} doc={doc} onOpenSlice={onOpenSlice} onOpenFlow={onOpenFlow} />))
    const row = [...host.querySelectorAll('tbody tr')].find((r) => r.textContent?.includes('AUD_READ'))!
    expect(row.textContent).toContain('문서')
    act(() => { row.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 100, clientY: 100 })) })
    const pop = host.querySelector('[role="dialog"]')!
    expect(pop.textContent).toContain('hand-off 문서에 선언된 loop 주기')
    expect(pop.textContent).toContain('ABOX period · 50 Hz · independent loop')
    expect(pop.textContent).toContain('ABOX (50 Hz)')
    const btn = (re: RegExp) => [...pop.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
    act(() => { btn(/Full-stack/).dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(onOpenSlice).toHaveBeenCalledWith('aud.read#c0')
    act(() => { btn(/Processing flow · Audio period/).dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(onOpenFlow).toHaveBeenCalledWith('audio')
  })

  it('an aperiodic (kind: event) declaration wins over the capture / window period', () => {
    const evDoc: HandoffDoc = { ...doc, cadences: [{ id: 'touch', name: 'Touch', kind: 'event' }],
      flows: [{ id: 'touch', name: 'Touch', cadence: 'touch', steps: [{ to: 'hal', task: 'aud.read' }] }] }
    const row = cadenceRows(tl, evDoc).find((r) => r.task === 'aud.read')!
    expect(row.basis).toBe('doc')
    expect(row.period).toBeNull()
    expect(row.load).toBeNull()
    expect(cadenceRows(tl, doc).find((r) => r.task === 'aud.read')!.period).toBe(20)
  })
})
