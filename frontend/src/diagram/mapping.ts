// Pure mapping between timeline events and diagram graph nodes.
// Topology node ids look like "ip-isp0" / "csis0" while timeline events
// carry node_id "isp0" and resource_id "ISP0"; matching normalizes both
// sides and tolerates the "ip-" prefix.
import type { TimelineEvent } from '../engine/types'

export interface DiagramNode {
  id: string
  label: string
  type: string
  layer: string
}

export interface DiagramEdge {
  id: string
  source: string
  target: string
  flow_type: string
  label?: string
}

export interface DiagramGraph {
  nodes: DiagramNode[]
  edges: DiagramEdge[]
}

export function normalizeNodeKey(value: unknown): string {
  const text = String(value ?? '').trim().toLowerCase()
  if (!text) return ''
  return text.replace(/^ip-/, '')
}

/** Candidate keys an event can match a diagram node by, strongest first. */
export function eventNodeKeys(event: TimelineEvent): string[] {
  const keys = [event.node_id, event.resource_id, event.hw_name]
    .map(normalizeNodeKey)
    .filter((key) => key.length > 0)
  return [...new Set(keys)]
}

/** Diagram node id matching the event, or null. */
export function matchDiagramNode(nodes: DiagramNode[], event: TimelineEvent): string | null {
  const keys = eventNodeKeys(event)
  if (!keys.length) return null
  for (const key of keys) {
    for (const node of nodes) {
      const nodeKey = normalizeNodeKey(node.id)
      if (nodeKey === key || normalizeNodeKey(node.label) === key) {
        return node.id
      }
    }
  }
  return null
}

/** Events belonging to the diagram node (for reverse cross-probe). */
export function eventsForDiagramNode(events: TimelineEvent[], nodeId: string, nodeLabel = ''): TimelineEvent[] {
  const nodeKeys = new Set([normalizeNodeKey(nodeId), normalizeNodeKey(nodeLabel)].filter(Boolean))
  return events.filter((event) => eventNodeKeys(event).some((key) => nodeKeys.has(key)))
}
