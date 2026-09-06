import { describe, expect, it } from 'vitest'
import { buildFlowEdges, criticalFlowEdges, flowsForTask } from '../src/engine/flows'
import type { TimelineEvent } from '../src/engine/types'

function event(partial: Partial<TimelineEvent>): TimelineEvent {
  return { task_id: 'task', start_ms: 0, end_ms: 1, duration_ms: 1, ...partial }
}

const EVENTS = [
  event({ task_id: 'sensor#f0' }),
  event({ task_id: 'isp#f0', predecessors: ['sensor#f0'], critical: true }),
  event({ task_id: 'dma#f0', predecessors: ['isp#f0'], critical: true }),
  event({ task_id: 'sw#f0', predecessors: ['dma#f0', 'ghost#f0'] }),
]

describe('buildFlowEdges', () => {
  it('derives edges from predecessors and drops missing endpoints', () => {
    const edges = buildFlowEdges(EVENTS)
    expect(edges.map((e) => `${e.fromId}->${e.toId}`)).toEqual([
      'sensor#f0->isp#f0',
      'isp#f0->dma#f0',
      'dma#f0->sw#f0',
    ])
  })

  it('marks an edge critical only when both endpoints are critical', () => {
    const edges = buildFlowEdges(EVENTS)
    expect(edges.find((e) => e.toId === 'isp#f0')?.critical).toBe(false)
    expect(edges.find((e) => e.toId === 'dma#f0')?.critical).toBe(true)
    expect(edges.find((e) => e.toId === 'sw#f0')?.critical).toBe(false)
  })
})

describe('flowsForTask', () => {
  it('returns incoming and outgoing edges of the task', () => {
    const edges = buildFlowEdges(EVENTS)
    const flows = flowsForTask(edges, 'isp#f0')
    expect(flows.map((e) => `${e.fromId}->${e.toId}`)).toEqual([
      'sensor#f0->isp#f0',
      'isp#f0->dma#f0',
    ])
  })
})

describe('criticalFlowEdges', () => {
  it('keeps only fully-critical edges', () => {
    const edges = criticalFlowEdges(buildFlowEdges(EVENTS))
    expect(edges.map((e) => `${e.fromId}->${e.toId}`)).toEqual(['isp#f0->dma#f0'])
  })
})
