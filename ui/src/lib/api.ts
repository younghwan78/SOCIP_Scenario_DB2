// Thin client for the ScenarioDB FastAPI read endpoints (served under /api/v1).
export const API_BASE: string = (import.meta.env.VITE_SCENARIODB_API_BASE as string | undefined) ?? '/api/v1'

export type Dict = Record<string, unknown>

export interface Paged<T> { items: T[]; total: number }

export interface CatalogItem {
  project_id: string
  scenario_id: string
  scenario_name: string
  category: string[]
  domain: string[]
  variant_count: number
  severity_counts: Record<string, number>
  node_count: number
  edge_count: number
  buffer_count: number
  default_variant_id?: string | null
  soc_ref?: string | null
  board_type?: string | null
}

export interface VariantRow {
  project_id: string
  scenario_id: string
  scenario_name?: string
  category?: string[]
  variant_id: string
  severity?: string | null
  design_conditions: Dict
  derived_from_variant?: string | null
  own_condition_keys?: string[]
}

export interface ResolvedVariant {
  id: string
  scenario_id: string
  severity?: string | null
  design_conditions?: Dict | null
  derived_from_variant?: string | null
  tags?: string[] | null
}

export interface ViewNodeData {
  id: string
  label: string
  type: string
  layer?: string
  parent?: string | null
  ip_ref?: string | null
  active_operations?: Dict | null
  memory?: Dict | null
  capability_badges?: string[]
  dma_count?: number | null
}

export interface ViewEdgeData {
  id: string
  source: string
  target: string
  flow_type: 'OTF' | 'vOTF' | 'M2M' | 'control' | 'risk'
  buffer_ref?: string | null
  producer?: string | null
  consumer?: string | null
  port_pairs?: { src: string; dst: string }[]
  memory?: Dict | null
}

export interface ViewResponse {
  level: number
  scenario_id: string
  variant_id: string
  nodes: { data: ViewNodeData }[]
  edges: { data: ViewEdgeData }[]
  summary: { name: string; subtitle: string; period_ms: number; budget_ms: number; fps?: number; resolution?: string }
}

export interface Evidence {
  id: string
  kind: string
  scenario_ref?: string
  variant_ref?: string
  project_ref?: string
  execution_context?: Dict | null
  kpi?: Dict | null
  vdd_power?: Dict | null
  provenance?: Dict | null
  profiling_metadata?: Dict | null
  timeline_events?: TimelineEvent[] | null
}

export interface TimelineEvent {
  task_id: string
  node_id?: string | null
  start_ms: number
  end_ms: number
  frame_index?: number | null
  predecessors?: string[]
  resource_name?: string | null
  resource_id?: string | null
  hw_name?: string | null
  task_type?: string | null
  logical_task_id?: string | null
  source_slice_name?: string | null
  critical?: boolean
}

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) { super(message) }
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  if (!entries.length) return ''
  return '?' + entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join('&')
}

const cache = new Map<string, Promise<unknown>>()

export async function getJson<T>(path: string, params: Record<string, string | number | undefined | null> = {}, useCache = true): Promise<T> {
  const url = `${API_BASE}${path}${qs(params)}`
  if (useCache && cache.has(url)) return cache.get(url) as Promise<T>
  const promise = fetch(url).then(async (res) => {
    if (!res.ok) throw new ApiError(`${res.status} ${res.statusText} — ${path}`, res.status)
    return res.json() as Promise<T>
  })
  if (useCache) {
    cache.set(url, promise)
    promise.catch(() => cache.delete(url))
  }
  return promise
}

const enc = encodeURIComponent

export const api = {
  health: () => getJson<Dict>('/explorer/summary', {}, false),
  summary: (projectRef?: string) => getJson<Dict>('/explorer/summary', { project_ref: projectRef }),
  catalog: (projectRef?: string) => getJson<{ items: CatalogItem[]; total: number }>('/explorer/scenario-catalog', { project_ref: projectRef, limit: 1000 }),
  matrix: (projectRef?: string) => getJson<{ items: VariantRow[]; total: number; axis_keys: string[] }>('/explorer/variant-matrix', { project_ref: projectRef, limit: 5000 }),
  projects: () => getJson<Paged<{ id: string; metadata_?: Dict }>>('/projects', { limit: 500 }),
  socs: () => getJson<Paged<{ id: string }>>('/soc-platforms', { limit: 500 }),
  variants: (scenarioId: string) => getJson<Paged<ResolvedVariant>>(`/scenarios/${enc(scenarioId)}/variants`, { limit: 1000 }),
  view: (scenarioId: string, variantId: string, level = 1) => getJson<ViewResponse>(`/scenarios/${enc(scenarioId)}/variants/${enc(variantId)}/view`, { level }),
  evidenceList: (scenarioId: string, variantId: string) => getJson<Paged<Evidence>>('/evidence', { scenario_ref: scenarioId, variant_ref: variantId, limit: 200 }),
  evidence: (id: string) => getJson<Evidence>(`/evidence/${enc(id)}`),
  predMeas: (predictionId: string, measurementId: string) => getJson<{ rows: Dict[]; summary: Dict; context: Dict }>('/compare/prediction-measurement', { prediction_id: predictionId, measurement_id: measurementId }),
}
