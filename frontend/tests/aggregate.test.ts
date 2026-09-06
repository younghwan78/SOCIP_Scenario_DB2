import { describe, expect, it } from 'vitest'
import { eventsInRange, rangeStats } from '../src/engine/aggregate'
import type { TimelineEvent } from '../src/engine/types'

function event(partial: Partial<TimelineEvent>): TimelineEvent {
  return { task_id: 'task', start_ms: 0, end_ms: 1, duration_ms: 1, ...partial }
}

const EVENTS = [
  event({ task_id: 'a', start_ms: 0, end_ms: 10, resource_wait_ms: 2, critical: true }),
  event({ task_id: 'b', start_ms: 5, end_ms: 15, token_wait_ms: 1.5 }),
  event({ task_id: 'c', start_ms: 20, end_ms: 30 }),
]

describe('eventsInRange', () => {
  it('returns intersecting events only', () => {
    expect(eventsInRange(EVENTS, 4, 6).map((e) => e.task_id)).toEqual(['a', 'b'])
    expect(eventsInRange(EVENTS, 16, 19)).toHaveLength(0)
  })

  it('treats interval ends as exclusive touch points', () => {
    expect(eventsInRange(EVENTS, 10, 12).map((e) => e.task_id)).toEqual(['b'])
  })
})

describe('rangeStats', () => {
  it('clips busy time to the range and sums waits', () => {
    const stats = rangeStats(EVENTS, 4, 6)
    expect(stats.eventCount).toBe(2)
    expect(stats.busyMs).toBeCloseTo(3) // a: 4..6 (2ms) + b: 5..6 (1ms)
    expect(stats.resourceWaitMs).toBeCloseTo(2)
    expect(stats.tokenWaitMs).toBeCloseTo(1.5)
    expect(stats.criticalCount).toBe(1)
  })

  it('normalizes reversed ranges', () => {
    expect(rangeStats(EVENTS, 6, 4)).toEqual(rangeStats(EVENTS, 4, 6))
  })

  it('returns zeros for an empty range', () => {
    const stats = rangeStats(EVENTS, 100, 110)
    expect(stats.eventCount).toBe(0)
    expect(stats.busyMs).toBe(0)
  })
})
