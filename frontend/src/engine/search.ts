// Pure search helpers for the timeline search-jump feature.
import type { TimelineEvent } from './types'

export function findMatches(events: TimelineEvent[], query: string): TimelineEvent[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return []
  return events.filter((event) => {
    const haystack = `${event.task_id} ${event.hw_name ?? ''} ${event.node_id ?? ''} ${event.resource_id ?? ''}`.toLowerCase()
    return haystack.includes(needle)
  })
}
