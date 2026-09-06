import { describe, expect, it } from 'vitest'
import { findMatches } from '../src/engine/search'
import type { TimelineEvent } from '../src/engine/types'

function event(partial: Partial<TimelineEvent>): TimelineEvent {
  return { task_id: 'task', start_ms: 0, end_ms: 1, duration_ms: 1, ...partial }
}

const EVENTS = [
  event({ task_id: 'isp0#f0', hw_name: 'ISP0' }),
  event({ task_id: 'isp0#f1', hw_name: 'ISP0' }),
  event({ task_id: 'dma_copy#f0', resource_id: 'DMA0' }),
  event({ task_id: 'sw_post#f0', node_id: 'cpu_big' }),
]

describe('findMatches', () => {
  it('matches task id substrings case-insensitively', () => {
    expect(findMatches(EVENTS, 'ISP0').map((e) => e.task_id)).toEqual(['isp0#f0', 'isp0#f1'])
  })

  it('matches resource and node fields', () => {
    expect(findMatches(EVENTS, 'dma0')).toHaveLength(1)
    expect(findMatches(EVENTS, 'cpu_big')).toHaveLength(1)
  })

  it('returns empty for blank or missing queries', () => {
    expect(findMatches(EVENTS, '  ')).toEqual([])
    expect(findMatches(EVENTS, 'zzz')).toEqual([])
  })
})
