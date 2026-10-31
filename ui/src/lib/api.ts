// Thin client for the ScenarioDB FastAPI read endpoints (served under /api/v1).
import { fetchAdmitted } from './admission'
import { authVersion } from './auth'
import { currentReadSignal } from './readRequestScope'
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
  /** variant-matrix: LLC-resident / compressed buffers and vOTF links of the resolved variant */
  memory_levers?: MemoryLevers
}

export interface MemoryLevers {
  llc?: string[]; compressed?: string[]; votf?: string[]; llc_weight_min?: number | null
  /** LLC MB allocated in this variant (sum of owner partitions) · owners · LLC buffers without a size */
  llc_mb?: number | null; llc_owners?: string[]; llc_unsized?: number
  /** WDMA/RDMA ports moving a compressed (SBWC/AFBC) buffer */
  compressed_dma?: number
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
  /** LLC placement of the buffer (llc_allocated / llc_allocation_mb / llc_policy / allocation_owner / llc_weight) */
  placement?: Dict | null
  latency_class?: 'streaming' | 'line_delayed' | 'frame_buffered' | null
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
  /** measurement: in-house hand-off order (sdb.handoff/1), drawn on Behavior / 처리 흐름 */
  handoff_flows?: HandoffDoc | null
  /** simulation: tool (scenariodb-sim = Simulate 기본 조건, scenariodb-timing-budget = Timing Budget 조건), timestamp, config profile, writer */
  run_info?: Dict | null
  measured_at?: string | null
}

/** sdb.handoff/1 — docs/design/handoff-flow-ko.md (validated on import; layer / kind values as in the backend model) */
export interface HandoffParticipant { id: string; layer: string; name: string; detail?: string }
export interface HandoffCadence { id: string; name: string; kind: 'frame' | 'vsync' | 'period' | 'chunk' | 'divided' | 'event'; period_ms?: number; of?: string; every?: number; note?: string }
export interface HandoffStep {
  from?: string; to?: string; call?: string; task?: string; slice?: string; node?: string
  handoff?: string; branch?: string; cadence?: string; every?: number; frame_offset?: number
  t_ms?: number; dur_ms?: number; note?: string; over?: string[]
}
export interface HandoffFlow { id: string; name: string; cadence: string; summary?: string; steps: HandoffStep[] }
export interface HandoffDoc { format: 'sdb.handoff/1'; generator?: string; participants: HandoffParticipant[]; cadences: HandoffCadence[]; flows: HandoffFlow[] }

export interface BehaviorEntry { scenario_ref: string; variant_ref: string; evidence_ids: string[]; full_stack: boolean; flows: number }

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
  /** full-stack trace: app | framework | hal | kernel | fw | hw (absent on pipeline traces) */
  layer?: string | null
  process?: string | null
  thread?: string | null
  /** hand-off into this slice: kick | complete | ipc | irq | data */
  handoff?: string | null
  /** own-cadence work (ABOX, AAC, chunk write …): period over the full capture */
  cadence_period_ms?: number | null
  independent_period_ms?: number | null
}

export interface BufferDef {
  size_ref?: string
  format?: string
  bitdepth?: number
  compression?: string
  comp_ratio?: number
  /** LLC placement (llc_allocated, llc_weight = DRAM factor, llc_allocation_mb, llc_policy, allocation_owner) */
  placement?: Dict
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

/** GET …/sim-inputs — what the simulation charges per node (Pipeline "Sim 입력" lens). */
export interface SimInputRow {
  node_id: string
  ip_ref?: string | null
  role?: string | null
  kind: 'hw' | 'sw'
  cadence: { path: 'frame' | 'independent'; rate_hz: number | null; period_ms: number | null; per_frame: number | null; value_source?: string | null }
  duration: { mean_ms: number | null; min_ms?: number | null; max_ms?: number | null; p95_ms?: number | null; basis: string; value_source?: string | null } | null
  load: { cpu_ms_per_s?: number; duty_pct?: number; wall_ms_per_s?: number; included_hw_ms?: number; cpu_active_ratio?: number } | null
  power: { mw: number | null; basis: string; status?: string | null } | null
  bw_mbs: { read: number; write: number } | null
}
export interface SimInputCheck { kind: 'value' | 'rate' | 'add' | 'info'; node_id: string | null; title: string; detail: string }
export interface SimInputs {
  scenario_id: string
  variant_id: string
  fps: number | null
  timing_case: string
  simulation_ref: string | null
  measurement_ref: string | null
  rows: SimInputRow[]
  totals: { sw_cpu_ms_per_s: number; independent_nodes: number }
  checks: SimInputCheck[]
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


interface ReadRequest {
  promise: Promise<unknown>; expires: number; controller: AbortController; subscribers: number; pending: boolean
}
const cache = new Map<string, ReadRequest>()
const inflight = new Map<string, ReadRequest>()

/** New readers must start after the write; existing subscribers may finish their original read. */
export function invalidateCache(prefix: string): void {
  for (const k of [...cache.keys()]) if (k.startsWith(`${API_BASE}${prefix}`)) cache.delete(k)
  for (const k of [...inflight.keys()]) if (k.startsWith(`${API_BASE}${prefix}`)) inflight.delete(k)
}

function subscribeRead<T>(entry: ReadRequest, key: string, signal?: AbortSignal): Promise<T> {
  if (signal?.aborted) return Promise.reject(signal.reason ?? new DOMException('Aborted', 'AbortError'))
  entry.subscribers++
  return new Promise<T>((resolve, reject) => {
    let done = false
    const release = () => {
      if (done) return false
      done = true; signal?.removeEventListener('abort', abort); entry.subscribers--
      if (entry.pending && entry.subscribers === 0) {
        if (cache.get(key) === entry) cache.delete(key)
        if (inflight.get(key) === entry) inflight.delete(key)
        entry.controller.abort()
      }
      return true
    }
    const abort = () => { if (release()) reject(signal?.reason ?? new DOMException('Aborted', 'AbortError')) }
    signal?.addEventListener('abort', abort, { once: true })
    entry.promise.then((value) => { if (release()) resolve(value as T) }, (error: unknown) => { if (release()) reject(error) })
  })
}

export async function getJson<T>(path: string, params: Record<string, string | number | undefined | null> = {}, useCache = true, signal = currentReadSignal()): Promise<T> {
  if (signal?.aborted) throw signal.reason ?? new DOMException('Aborted', 'AbortError')
  const url = `${API_BASE}${path}${qs(params)}`
  const cacheKey = `${url}|auth:${authVersion()}`
  const cached = cache.get(cacheKey)
  if (useCache && cached && cached.expires > Date.now()) return subscribeRead<T>(cached, cacheKey, signal)
  // uncached reads still share one request while it is in flight (StrictMode double effects, two panels at once)
  const flying = inflight.get(cacheKey)
  if (flying) return subscribeRead<T>(flying, cacheKey, signal)
  const controller = new AbortController()
  const promise = fetchAdmitted(url, { signal: controller.signal }).then(async (res) => {
    if (!res.ok) {
      let detail = ''
      try { const body = await res.json() as Dict; detail = (typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)).slice(0, 300) } catch { /* non-JSON response */ }
      throw new ApiError(`${res.status} ${res.statusText} — ${path}${detail ? ` · ${detail}` : ''}`, res.status)
    }
    return res.json() as Promise<T>
  })
  const entry: ReadRequest = { promise, expires: Date.now() + 60000, controller, subscribers: 0, pending: true }
  inflight.set(cacheKey, entry)
  const done = () => { entry.pending = false; if (inflight.get(cacheKey) === entry) inflight.delete(cacheKey) }
  promise.then(done, done)
  if (useCache) {
    if (cache.size >= 100) cache.delete(cache.keys().next().value!)
    cache.set(cacheKey, entry)
    promise.catch(() => { if (cache.get(cacheKey) === entry) cache.delete(cacheKey) })
  }
  return subscribeRead<T>(entry, cacheKey, signal)
}

export async function requestJson<T>(method: 'POST' | 'PUT' | 'PATCH', path: string, body: unknown): Promise<T> {
  const res = await fetchAdmitted(`${API_BASE}${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!res.ok) {
    let detail = ''
    try { const j = await res.json() as Dict; detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j).slice(0, 300) } catch { /* not JSON */ }
    throw new ApiError(`${res.status} ${res.statusText} — ${path}${detail ? `: ${detail}` : ''}`, res.status)
  }
  return res.json() as Promise<T>
}
export const postJson = <T>(path: string, body: unknown) => requestJson<T>('POST', path, body)

export interface SimRunRequest {
  scenario_id: string
  variant_id: string
  config_profile_ref?: string | null
  execution_context: { silicon_rev: string; sw_baseline_ref: string; thermal: string; method?: string }
  persist?: boolean
  expected_params_hash?: string
}
export interface SimRunResponse { evidence_id: string; kpi: Dict; warnings?: string[]; persisted?: boolean; cached?: boolean; params_hash?: string; evidence?: Dict | null; result?: { power_breakdown?: Dict | null; cpu_breakdown?: Dict[] | null } | null }

const enc = encodeURIComponent

async function allPages<T, P extends Paged<T> = Paged<T>>(path: string, params: Record<string, string | number | undefined> = {}, limit = 500, signal = currentReadSignal()): Promise<P> {
  const first = await getJson<P>(path, { ...params, limit, offset: 0 }, true, signal)
  const items = [...first.items]
  while (items.length < first.total) {
    const page = await getJson<P>(path, { ...params, limit, offset: items.length }, true, signal)
    if (!page.items.length) throw new ApiError(`목록이 변경되었습니다. 새로고침하세요 — ${path}`)
    items.push(...page.items)
  }
  return { ...first, items }
}

export const api = {
  health: () => getJson<Dict>('/explorer/summary', {}, false),
  summary: (projectRef?: string) => getJson<Dict>('/explorer/summary', { project_ref: projectRef }),
  catalog: (projectRef?: string) => allPages<CatalogItem>('/explorer/scenario-catalog', { project_ref: projectRef }),
  matrix: (projectRef?: string, scenarioId?: string) => allPages<VariantRow, Paged<VariantRow> & { axis_keys: string[] }>('/explorer/variant-matrix', { project_ref: projectRef, scenario_id: scenarioId }, 1000),
  projects: () => getJson<Paged<{ id: string; metadata_?: Dict }>>('/projects', { limit: 500 }),
  socs: () => getJson<Paged<{ id: string }>>('/soc-platforms', { limit: 500 }),
  variants: (scenarioId: string) => allPages<ResolvedVariant>(`/scenarios/${enc(scenarioId)}/variants`),
  view: (scenarioId: string, variantId: string, level = 1) => getJson<ViewResponse>(variantId ? `/scenarios/${enc(scenarioId)}/variants/${enc(variantId)}/view` : `/scenarios/${enc(scenarioId)}/view`, { level }),
  scenario: (scenarioId: string) => getJson<ScenarioDef>(`/scenarios/${enc(scenarioId)}`),
  variant: (scenarioId: string, variantId: string) => getJson<VariantDetail>(`/scenarios/${enc(scenarioId)}/variants/${enc(variantId)}`),
  simInputs: (scenarioId: string, variantId: string) => getJson<SimInputs>(`/scenarios/${enc(scenarioId)}/variants/${enc(variantId)}/sim-inputs`),
  /** variants with a full-stack trace or a sdb.handoff/1 document (Scenario page Behavior filter) */
  behaviorIndex: (project?: string) => getJson<BehaviorEntry[]>(`/behavior/index${project ? `?project_ref=${enc(project)}` : ''}`),
  ipCatalog: (ipId: string) => getJson<IpCatalog>(`/ip-catalogs/${enc(ipId)}`),
  evidenceList: (scenarioId: string, variantId: string, projectRef?: string) => allPages<Evidence>('/evidence', { scenario_ref: scenarioId, variant_ref: variantId, project_ref: projectRef }, 200),
  evidence: (id: string) => getJson<Evidence>(`/evidence/${enc(id)}`),
  simConfigs: (projectRef: string) => getJson<Paged<{ id: string; status?: string; version?: number; description?: string | null; approved_by?: string | null; run_config?: { vbat?: number | null; pmic_efficiency?: number | null; [k: string]: unknown } }>>('/sim-config-profiles', { project_ref: projectRef, limit: 50 }),
  simulate: (req: SimRunRequest) => postJson<SimRunResponse>('/simulation/run', { persist: false, ...req }),
  predMeas: (predictionId: string, measurementId: string) => getJson<{ rows: Dict[]; summary: Dict; context: Dict }>('/compare/prediction-measurement', { prediction_id: predictionId, measurement_id: measurementId }),
}
