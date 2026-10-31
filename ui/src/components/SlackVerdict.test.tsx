// @vitest-environment jsdom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it } from 'vitest'
import { VerdictBadge } from './RebalanceView'
import { schedText, slackVerdict, slackVerdictNote, type RbSplit } from '../lib/rebalance'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
// uhd30-vdis best case: post_crta meets 0.538 ms on its own time (0.4023) but shares a CPU with ~11.8 ms of co-runners
const split = (over: Partial<RbSplit> = {}): RbSplit => ({
  assign: {}, moved: [], total_mw: 300, delta_mw: -20, feasible: true, mw: {}, mhz: {}, mv: {}, busy_mhz: {}, dsu_active: 0.5, knobs: [],
  task_ms: { post_crta: 0.4023, eis: 3.1 }, slack_ms: { post_crta: 0.1357, eis: 2.0 }, min_slack_ms: 0.1357,
  response_ms: { post_crta: 12.2326, eis: 3.5 }, min_slack_shared_ms: -11.6946, ...over,
})

describe('CPU rebalance slack verdict', () => {
  it('own slack decides; a negative shared bound only makes it conditional and names the task', () => {
    const v = slackVerdict(split())
    expect(v.tier).toBe('shared')
    expect(v.task).toBe('post_crta')
    expect(v.shared_ms).toBeCloseTo(-11.6946, 3)
    expect(v.wait_ms).toBeCloseTo(11.8303, 3)
    expect(slackVerdictNote(v)).toContain('우선순위 미지정')
  })
  it('ok when every shared task still meets its budget, miss when infeasible', () => {
    expect(slackVerdict(split({ response_ms: { post_crta: 0.5, eis: 3.5 }, min_slack_shared_ms: 0.038 })).tier).toBe('ok')
    expect(slackVerdict(split({ response_ms: {}, min_slack_shared_ms: null })).tier).toBe('ok')
    expect(slackVerdict(split({ feasible: false })).tier).toBe('miss')
    // rounding noise at zero is not a risk
    expect(slackVerdict(split({ response_ms: { post_crta: 0.5383 }, min_slack_shared_ms: -0.0003 })).tier).toBe('ok')
  })
  it('a split without the co-runner check (move-curve point) is unchecked, not 충족', () => {
    const v = slackVerdict(split({ response_ms: undefined, min_slack_shared_ms: undefined }))
    expect(v.tier).toBe('unchecked')
    expect(slackVerdictNote(v)).toContain('검사하지 않음')
  })
  it('falls back to the minimum when an older server sends no per-task response', () => {
    const v = slackVerdict(split({ response_ms: undefined, min_slack_shared_ms: -2 }))
    expect(v).toEqual({ tier: 'shared', basis: 'bound', shared_ms: -2 })
  })
  it('badge shows the verdict, never the negative shared bound as the slack', () => {
    const host = document.createElement('div'); document.body.appendChild(host)
    const root = createRoot(host)
    act(() => root.render(createElement('div', null, createElement(VerdictBadge, { s: split() }), createElement(VerdictBadge, { s: split(), long: true }))))
    const [short, long] = host.querySelectorAll('.rb-verdict')
    expect(short.textContent).toBe('조건부')
    expect(short.className).toContain('v-warn')
    expect(short.getAttribute('title')).toContain('post_crta: slack -11.69 ms')
    expect(long.textContent).toBe('조건부 충족 · post_crta 대기 시 -11.69 ms')
    act(() => root.unmount())
  })
  it('with task_policy priorities the class / priority wait decides: RT post_crta meets, a normal co-runner can miss', () => {
    // post_crta FIFO: waits for no normal co-runner; eis nice −10 behind post_crta + camera_hal_request's share
    const rt = split({ response_prio_ms: { post_crta: 0.4023, eis: 3.5 }, min_slack_prio_ms: 0.1357 })
    expect(slackVerdict(rt)).toEqual({ tier: 'ok', basis: 'priority' })
    const host = document.createElement('div'); document.body.appendChild(host)
    const root = createRoot(host)
    act(() => root.render(createElement(VerdictBadge, { s: rt, long: true })))
    expect(host.textContent).toBe('충족 · 우선순위 반영')
    act(() => root.unmount())
    const miss = slackVerdict(split({ response_prio_ms: { post_crta: 0.4023, eis: 6.0 }, min_slack_prio_ms: -0.9 }))
    expect(miss).toMatchObject({ tier: 'wait_miss', basis: 'priority', task: 'eis' })
    expect(miss.shared_ms).toBeCloseTo(2.0 - 2.9, 3)
    expect(slackVerdictNote(miss)).toContain('우선순위 상향')
    // no priorities: the bound can only say 조건부, and the note says how to decide it
    expect(slackVerdictNote(slackVerdict(split()))).toContain('sched_class')
  })
  it('names the scheduling class compactly', () => {
    expect(schedText({ sched_class: 'fifo', rt_priority: 2 })).toBe('FIFO 2')
    expect(schedText({ sched_class: 'normal', nice: -10 })).toBe('nice −10')
    expect(schedText({ sched_class: 'normal' })).toBe('nice 0')
    expect(schedText(undefined)).toBeNull()
  })
})
