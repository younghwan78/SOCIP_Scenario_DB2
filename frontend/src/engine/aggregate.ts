// Pure range-selection statistics for the brush selection footer and the
// value returned to Streamlit. Semantics: events whose [start, end) interval
// intersects the selected range; busyMs is clipped to the range, wait sums
// are whole-event values for intersecting events.
import type { RangeStats, TimelineEvent } from './types'
import { eventEnd, eventStart } from './types'

export function eventsInRange(events: TimelineEvent[], startMs: number, endMs: number): TimelineEvent[] {
  const lo = Math.min(startMs, endMs)
  const hi = Math.max(startMs, endMs)
  return events.filter((event) => eventEnd(event) > lo && eventStart(event) < hi)
}

export function rangeStats(events: TimelineEvent[], startMs: number, endMs: number): RangeStats {
  const lo = Math.min(startMs, endMs)
  const hi = Math.max(startMs, endMs)
  const hits = eventsInRange(events, lo, hi)
  let busyMs = 0
  let resourceWaitMs = 0
  let tokenWaitMs = 0
  let criticalCount = 0
  for (const event of hits) {
    busyMs += Math.max(0, Math.min(eventEnd(event), hi) - Math.max(eventStart(event), lo))
    resourceWaitMs += event.resource_wait_ms ?? 0
    tokenWaitMs += event.token_wait_ms ?? 0
    if (event.critical) criticalCount += 1
  }
  return {
    eventCount: hits.length,
    busyMs,
    resourceWaitMs,
    tokenWaitMs,
    criticalCount,
  }
}
