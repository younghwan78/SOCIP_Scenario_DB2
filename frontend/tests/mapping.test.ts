import { describe, expect, it } from 'vitest'
import { eventNodeKeys, eventsForDiagramNode, matchDiagramNode, normalizeNodeKey } from '../src/diagram/mapping'
import type { TimelineEvent } from '../src/engine/types'

function event(partial: Partial<TimelineEvent>): TimelineEvent {
  return { task_id: 'task', start_ms: 0, end_ms: 1, duration_ms: 1, ...partial }
}

const NODES = [
  { id: 'ip-isp0', label: 'ISP0', type: 'ip', layer: 'hw' },
  { id: 'csis0', label: 'CSIS0', type: 'ip', layer: 'hw' },
  { id: 'buf-record', label: 'Record Buf', type: 'buffer', layer: 'memory' },
]

describe('normalizeNodeKey', () => {
  it('lowercases and strips the ip- prefix', () => {
    expect(normalizeNodeKey('ip-ISP0')).toBe('isp0')
    expect(normalizeNodeKey(' CSIS0 ')).toBe('csis0')
    expect(normalizeNodeKey(null)).toBe('')
  })
})

describe('matchDiagramNode', () => {
  it('matches by node_id against prefixed ids', () => {
    expect(matchDiagramNode(NODES, event({ node_id: 'isp0' }))).toBe('ip-isp0')
  })

  it('falls back to resource and hw name', () => {
    expect(matchDiagramNode(NODES, event({ resource_id: 'CSIS0' }))).toBe('csis0')
    expect(matchDiagramNode(NODES, event({ hw_name: 'ISP0' }))).toBe('ip-isp0')
  })

  it('returns null when nothing matches', () => {
    expect(matchDiagramNode(NODES, event({ node_id: 'npu' }))).toBeNull()
    expect(matchDiagramNode(NODES, event({}))).toBeNull()
  })
})

describe('eventsForDiagramNode', () => {
  it('collects the events belonging to a node across frames', () => {
    const events = [
      event({ task_id: 'a#f0', node_id: 'isp0' }),
      event({ task_id: 'a#f1', node_id: 'isp0' }),
      event({ task_id: 'b#f0', node_id: 'csis0' }),
    ]
    expect(eventsForDiagramNode(events, 'ip-isp0', 'ISP0')).toHaveLength(2)
    expect(eventsForDiagramNode(events, 'csis0')).toHaveLength(1)
  })
})

describe('eventNodeKeys', () => {
  it('dedupes candidates', () => {
    expect(eventNodeKeys(event({ node_id: 'isp0', resource_id: 'ISP0', hw_name: 'isp0' }))).toEqual(['isp0'])
  })
})
