// Perfetto-style flow edges derived from timeline event `predecessors`.
// Pure module: edge derivation is unit-tested, rendering lives in the engine.
import type { TimelineEvent } from './types'

export interface FlowEdge {
  fromId: string
  toId: string
  critical: boolean
}

/** Dependency edges between events of the visible set (both endpoints present). */
export function buildFlowEdges(events: TimelineEvent[]): FlowEdge[] {
  const byId = new Map<string, TimelineEvent>()
  for (const event of events) {
    byId.set(String(event.task_id), event)
  }
  const edges: FlowEdge[] = []
  for (const event of events) {
    for (const predecessor of event.predecessors ?? []) {
      const from = byId.get(String(predecessor))
      if (!from) continue
      edges.push({
        fromId: String(from.task_id),
        toId: String(event.task_id),
        critical: Boolean(from.critical) && Boolean(event.critical),
      })
    }
  }
  return edges
}

/** Incoming and outgoing flows of one task, for selected-slice highlighting. */
export function flowsForTask(edges: FlowEdge[], taskId: string): FlowEdge[] {
  return edges.filter((edge) => edge.fromId === taskId || edge.toId === taskId)
}

/** Edges whose both endpoints are on the critical path. */
export function criticalFlowEdges(edges: FlowEdge[]): FlowEdge[] {
  return edges.filter((edge) => edge.critical)
}
