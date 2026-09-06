export interface SocPlatform {
  id: string
  name: string
  vendor?: string
  generation?: string
  description?: string
  default_sw_profile_ref?: string
}

export interface Project {
  id: string
  name: string
  soc_ref: string
  board_type: string
  board_name?: string
  sensor_module_ref?: string
  display_module_ref?: string
  default_sw_profile_ref?: string
}

export interface Scenario {
  id: string
  soc_ref: string
  project_ref?: string
  name: string
  category: string
  description?: string
  variants_count?: number
  has_evidence?: boolean
}

export interface Variant {
  id: string
  scenario_id: string
  name: string
  description?: string
  parameters: Record<string, any>
  is_base?: boolean
}

export interface NodeElement {
  data: {
    id: string
    label: string
    type: string
    layer?: string
    module_kind?: string
    ip_ref?: string
    ip_group?: string
    subsystem?: string
    summary_badges?: string[]
    detail_items?: string[]
    placement?: {
      memory_type?: string
      llc_allocated?: boolean
      compression?: string
    }
  }
}

export interface EdgeElement {
  data: {
    id: string
    source: string
    target: string
    flow_type: 'OTF' | 'vOTF' | 'M2M' | 'control' | 'risk'
    label?: string
    buffer_ref?: string
    detail_items?: string[]
  }
}

export interface ViewResponse {
  scenario_id: string
  variant_id?: string
  level: number
  mode: 'architecture' | 'topology' | 'resource'
  nodes: NodeElement[]
  edges: EdgeElement[]
  summary: {
    total_nodes: number
    total_edges: number
    active_ips: number
    memory_footprint_mb?: number
  }
  metadata: {
    layout?: string
    canvas_w?: number
    canvas_h?: number
    [key: string]: any
  }
}

export interface TimelineEvent {
  task_id: string
  node_id?: string
  hw_name?: string
  task_type?: 'hw' | 'sw' | 'dma'
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
  end_ms: number
  duration_ms: number
  deadline_ms?: number
  slack_ms?: number
  cadence_interval_ms?: number
  cadence_avg_interval_ms?: number
  cadence_budget_ms?: number
  cadence_slack_ms?: number
  cadence_violation?: boolean
  ready_ms?: number
  resource_wait_ms?: number
  token_wait_ms?: number
  critical?: boolean
  critical_path_rank?: number
  bottleneck?: boolean
  bottleneck_reason?: string
  predecessors?: string[]
}

export interface SwTaskTiming {
  task: string
  cluster?: string
  mean_ms?: number
  p50_ms?: number
  p95_ms?: number
  max_ms?: number
  count_per_frame?: number
  samples?: number
}

export interface Evidence {
  isPreview?: boolean
  id: string
  schema_version: string
  kind: 'evidence.simulation' | 'evidence.measurement'
  scenario_ref: string
  variant_ref: string
  project_ref?: string
  measured_at?: string
  kpi: Record<string, any>
  timeline_events?: TimelineEvent[]
  sw_task_timing?: SwTaskTiming[]
  cpu_breakdown?: Array<{
    cluster: string
    avg_freq_mhz?: number
    util_pct?: number
    power_mw?: { mean?: number; p95?: number }
    freq_residency?: Array<{ freq_mhz: number; ratio: number; time_ms: number }>
  }>
  vdd_power?: Record<string, any>
  dma_breakdown?: Array<{
    node_id: string
    hw_name?: string
    port?: string
    direction?: string
    bw_mbs: number
    bw_power_mw?: number
  }>
  artifacts?: Array<{
    type: string
    path: string
    storage?: string
    sha256?: string
    bytes?: number
  }>
}
