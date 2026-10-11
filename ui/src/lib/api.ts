// Thin client for the ScenarioDB FastAPI read endpoints (served under /api/v1).
import { fetchAdmitted } from './admission'
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
  board_name?: string | null
  project_name?: string | null
  canonical_usecase?: string | null
  default_sw_profile_ref?: string | null
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
  power_breakdown?: Dict | null
  provenance?: Dict | null
  profiling_metadata?: Dict | null
  timeline_events?: TimelineEvent[] | null
  /** simulation: tool (scenariodb-sim = Simulate 기본 조건, scenariodb-timing-budget = Timing Budget 조건), timestamp, config profile, writer */
  run_info?: Dict | null
  measured_at?: string | null
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

export interface BufferDef {
  size_ref?: string
  format?: string
  bitdepth?: number
  compression?: string
  layer?: number
  size_status?: string
  source_note?: string
  history?: { node_id: string; frame_offset?: number; read_ports?: string[]; write_ports?: string[]; producer?: string; initialization?: string }
  dma?: { node_id: string; write_ports?: string[]; read_ports?: string[]; enabled?: boolean; activation_flag?: string }
}

export interface ScenarioDef {
  id: string
  metadata_?: Dict
  pipeline: { nodes?: { id: string; ip_ref?: string; role?: string }[]; buffers?: Record<string, BufferDef>; architecture_graph?: Dict }
  size_profile?: { anchors?: Record<string, string> } | null
}

export interface VariantDetail {
  id: string
  scenario_id: string
  design_conditions?: Dict | null
  size_overrides?: Record<string, string> | null
  node_configs?: Record<string, Dict> | null
  routing_switch?: { disabled_nodes?: string[] } | null
  buffer_overrides?: Record<string, Dict> | null
  tags?: string[] | null
}

export interface IpModule { name: string; type?: string; direction?: string; purpose?: string; lvn?: string; source_file?: string }
export interface IpCatalog {
  id: string
  category?: string | null
  rtl_version?: string | null
  capabilities?: { operating_modes?: { id: string }[]; properties?: { modules?: IpModule[]; ip_group?: string; hierarchy_group?: string; blk?: string; block?: string }; sim?: Dict } | null
}

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) { super(message) }
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  if (!entries.length) return ''
  return '?' + entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join('&')
}


const cache = new Map<string, { promise: Promise<unknown>; expires: number }>()

/** Drop cached GET responses whose path starts with ``prefix`` (after a write, e.g. a saved simulation). */
export function invalidateCache(prefix: string): void {
  for (const k of [...cache.keys()]) if (k.startsWith(`${API_BASE}${prefix}`)) cache.delete(k)
}

export async function getJson<T>(path: string, params: Record<string, string | number | undefined | null> = {}, useCache = true): Promise<T> {
  const url = `${API_BASE}${path}${qs(params)}`
  const cached = cache.get(url)
  if (useCache && cached && cached.expires > Date.now()) return cached.promise as Promise<T>
  const promise = fetchAdmitted(url, {}).then(async (res) => {
    if (!res.ok) throw new ApiError(`${res.status} ${res.statusText} — ${path}`, res.status)
    return res.json() as Promise<T>
  })
  if (useCache) {
    if (cache.size >= 100) cache.delete(cache.keys().next().value!)
    cache.set(url, { promise, expires: Date.now() + 60000 })
    promise.catch(() => { if (cache.get(url)?.promise === promise) cache.delete(url) })
  }
  return promise
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchAdmitted(`${API_BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!res.ok) {
    let detail = ''
    try { const j = await res.json() as Dict; detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j).slice(0, 300) } catch { /* not JSON */ }
    throw new ApiError(`${res.status} ${res.statusText} — ${path}${detail ? `: ${detail}` : ''}`, res.status)
  }
  return res.json() as Promise<T>
}

export interface SimRunRequest {
  scenario_id: string
  variant_id: string
  config_profile_ref?: string | null
  execution_context: { silicon_rev: string; sw_baseline_ref: string; thermal: string; method?: string }
  persist?: boolean
  expected_params_hash?: string
}
export interface SimRunResponse { evidence_id: string; kpi: Dict; warnings?: string[]; persisted?: boolean; cached?: boolean; params_hash?: string; evidence?: Dict | null; result?: { power_breakdown?: Dict | null } | null }

const enc = encodeURIComponent

async function allPages<T, P extends Paged<T> = Paged<T>>(path: string, params: Record<string, string | number | undefined> = {}, limit = 500): Promise<P> {
  const first = await getJson<P>(path, { ...params, limit, offset: 0 })
  const items = [...first.items]
  while (items.length < first.total) {
    const page = await getJson<P>(path, { ...params, limit, offset: items.length })
    if (!page.items.length) throw new ApiError(`목록이 변경되었습니다. 새로고침하세요 — ${path}`)
    items.push(...page.items)
  }
  return { ...first, items }
}

export const api = {
  health: () => getJson<Dict>('/explorer/summary', {}, false),
  summary: (projectRef?: string) => getJson<Dict>('/explorer/summary', { project_ref: projectRef }),
  catalog: (projectRef?: string) => allPages<CatalogItem>('/explorer/scenario-catalog', { project_ref: projectRef }),
  matrix: (projectRef?: string) => allPages<VariantRow, Paged<VariantRow> & { axis_keys: string[] }>('/explorer/variant-matrix', { project_ref: projectRef }, 1000),
  projects: () => getJson<Paged<{ id: string; metadata_?: Dict }>>('/projects', { limit: 500 }),
  socs: () => getJson<Paged<{ id: string }>>('/soc-platforms', { limit: 500 }),
  variants: (scenarioId: string) => allPages<ResolvedVariant>(`/scenarios/${enc(scenarioId)}/variants`),
  view: (scenarioId: string, variantId: string, level = 1) => getJson<ViewResponse>(variantId ? `/scenarios/${enc(scenarioId)}/variants/${enc(variantId)}/view` : `/scenarios/${enc(scenarioId)}/view`, { level }),
  scenario: (scenarioId: string) => getJson<ScenarioDef>(`/scenarios/${enc(scenarioId)}`),
  variant: (scenarioId: string, variantId: string) => getJson<VariantDetail>(`/scenarios/${enc(scenarioId)}/variants/${enc(variantId)}`),
  ipCatalog: (ipId: string) => getJson<IpCatalog>(`/ip-catalogs/${enc(ipId)}`),
  evidenceList: (scenarioId: string, variantId: string, projectRef?: string) => allPages<Evidence>('/evidence', { scenario_ref: scenarioId, variant_ref: variantId, project_ref: projectRef }, 200),
  evidence: (id: string) => getJson<Evidence>(`/evidence/${enc(id)}`),
  simConfigs: (projectRef: string) => getJson<Paged<{ id: string; status?: string; version?: number; description?: string | null; approved_by?: string | null; run_config?: { vbat?: number | null; pmic_efficiency?: number | null; [k: string]: unknown } }>>('/sim-config-profiles', { project_ref: projectRef, limit: 50 }),
  simulate: (req: SimRunRequest) => postJson<SimRunResponse>('/simulation/run', { persist: false, ...req }),
  predMeas: (predictionId: string, measurementId: string) => getJson<{ rows: Dict[]; summary: Dict; context: Dict }>('/compare/prediction-measurement', { prediction_id: predictionId, measurement_id: measurementId }),
}
