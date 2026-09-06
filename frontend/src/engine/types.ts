export interface TimelineEvent {
  task_id: string
  node_id?: string
  hw_name?: string
  task_type?: string
  frame_index?: number
  resource_id?: string
  edge_type?: string
  otf_group_id?: string
  constraint_type?: 'source' | 'sink'
  source_fps?: number
  v_valid_ms?: number
  refresh_hz?: number
  scanout_ms?: number
  start_ms: number
  end_ms?: number
  duration_ms?: number
  deadline_ms?: number | null
  slack_ms?: number | null
  cadence_interval_ms?: number | null
  cadence_avg_interval_ms?: number | null
  cadence_budget_ms?: number | null
  cadence_slack_ms?: number | null
  cadence_violation?: boolean
  ready_ms?: number | null
  resource_wait_ms?: number | null
  token_wait_ms?: number | null
  critical?: boolean
  critical_path_rank?: number
  bottleneck?: boolean
  bottleneck_reason?: string
  predecessors?: string[]
}

export type TrackCategory = 'sync_source' | 'hw_otf' | 'hw_m2m' | 'sw' | 'sync_sink' | 'misc'

export interface PlacedEvent {
  event: TimelineEvent
  lane: number
}

export interface TrackDefinition {
  id: string
  title: string
  category: TrackCategory
  color: string
  laneCount: number
  placed: PlacedEvent[]
  busyMs: number
}

export interface ViewportTransform {
  startMs: number
  endMs: number
  scale: number // pixels per ms
  offsetY: number // vertical scroll in px (<= 0)
}

export interface RangeStats {
  eventCount: number
  busyMs: number
  resourceWaitMs: number
  tokenWaitMs: number
  criticalCount: number
}

export interface SelectionState {
  selectedTaskId: string | null
  rangeStartMs: number | null
  rangeEndMs: number | null
  rangeStats: RangeStats | null
}

export interface DiagramExpandRequest {
  node: string | null
  seq: number
}

export interface WorkbenchOptions {
  showWaits: boolean
  showDeadlines: boolean
  theme: 'light' | 'dark'
  frameIntervalMs: number
}

export function eventStart(event: TimelineEvent): number {
  return event.start_ms ?? 0
}

export function eventEnd(event: TimelineEvent): number {
  if (event.end_ms !== undefined && event.end_ms !== null) return event.end_ms
  return eventStart(event) + (event.duration_ms ?? 0)
}
