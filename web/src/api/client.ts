import type { Evidence, Project, Scenario, SocPlatform, Variant, ViewResponse } from '../types'

const API_BASE = '/api/v1'
export interface Page<T> { items: T[]; total: number; limit: number; offset: number; has_next: boolean }
interface RawRecord { id: string; schema_version?: string; metadata_?: Record<string, unknown>; [key: string]: unknown }
export interface SimulationContext { silicon_rev: string; sw_baseline_ref: string; thermal: string; method: 'calculation' }
export interface Credentials { keyId: string; apiKey: string }
export interface SimulationResponse { evidence_id: string; evidence: Evidence | null; kpi: Record<string, number>; warnings: string[]; persisted: boolean }

export async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  if (options?.body) headers.set('Content-Type', 'application/json')
  const response = await fetch(`${API_BASE}${endpoint}`, { ...options, headers })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      const value = body.detail ?? body.message ?? detail
      detail = typeof value === 'string' ? value : JSON.stringify(value)
    } catch { /* retain HTTP status */ }
    throw new Error(`API Error [${response.status}]: ${detail}`)
  }
  return response.json()
}

async function allPages<T>(path: string, params = new URLSearchParams()): Promise<T[]> {
  const items: T[] = []
  const search = new URLSearchParams(params)
  search.set('limit', '1000')
  for (;;) {
    search.set('offset', String(items.length))
    const page = await request<Page<T>>(`${path}?${search}`)
    if (!Array.isArray(page.items)) throw new Error('Invalid paged API response')
    items.push(...page.items)
    if (!page.has_next) return items
    if (!page.items.length) throw new Error('API pagination did not advance')
  }
}
const text = (value: unknown, fallback = '') => typeof value === 'string' ? value : fallback

export const api = {
  getSocPlatforms: async (): Promise<SocPlatform[]> =>
    (await allPages<RawRecord>('/soc-platforms')).map(row => ({ id: row.id, name: text(row.name, row.id) })),
  getProjects: async (socRef?: string): Promise<Project[]> => {
    const rows = await allPages<RawRecord>('/projects', new URLSearchParams(socRef ? { soc_ref: socRef } : {}))
    return rows.map(row => ({ id: row.id, name: text(row.metadata_?.name, row.id),
      soc_ref: text(row.metadata_?.soc_ref), board_type: text(row.metadata_?.board_type),
      default_sw_profile_ref: text(row.metadata_?.default_sw_profile_ref) }))
  },
  getScenarios: async (params?: { soc_ref?: string; project_ref?: string; category?: string }): Promise<Scenario[]> => {
    const search = new URLSearchParams()
    if (params?.soc_ref) search.set('soc_ref', params.soc_ref)
    if (params?.project_ref) search.set('project_ref', params.project_ref)
    const rows = await allPages<RawRecord>('/scenarios', search)
    return rows.map(row => ({ id: row.id, name: text(row.metadata_?.name, row.id),
      project_ref: text(row.project_ref), soc_ref: text(row.metadata_?.soc_ref, params?.soc_ref),
      category: Array.isArray(row.metadata_?.category) ? row.metadata_.category.join(', ') : text(row.metadata_?.category) }))
      .filter(row => !params?.category || row.category.split(', ').includes(params.category))
  },
  getVariants: async (scenarioId: string, params?: { project?: string; soc_ref?: string }) => {
    const search = new URLSearchParams({ scenario_id: scenarioId })
    if (params?.project) search.set('project', params.project)
    if (params?.soc_ref) search.set('soc_ref', params.soc_ref)
    const rows = await allPages<RawRecord>('/variants', search)
    return { items: rows.map(row => ({ id: row.id, scenario_id: text(row.scenario_id, scenarioId), name: row.id,
      parameters: (row.design_conditions ?? {}) as Variant['parameters'] })) }
  },
  getView: (params: { scenarioId: string; variantId?: string; level?: number; mode?: string; expand?: string; sim?: string; simEvidenceId?: string }) => {
    const { scenarioId, variantId, level = 0, mode = 'architecture', expand, sim = 'none', simEvidenceId } = params
    const search = new URLSearchParams({ level: String(level), mode, sim })
    if (level === 2) search.set('expand', expand || 'camera')
    if (simEvidenceId) search.set('sim_evidence_id', simEvidenceId)
    const path = `/scenarios/${encodeURIComponent(scenarioId)}` + (variantId ? `/variants/${encodeURIComponent(variantId)}` : '')
    return request<ViewResponse>(`${path}/view?${search}`)
  },
  getLatestSimulation: async (scenarioId: string, variantId: string | null): Promise<Evidence | null> => {
    // Base views have no persisted variant; omitting this filter would select an unrelated variant.
    if (!variantId) return null
    const search = new URLSearchParams({ scenario_ref: scenarioId, variant_ref: variantId, latest: 'true', limit: '1' })
    const page = await request<Page<Evidence>>(`/simulation/results?${search}`)
    return page.items[0] ?? null
  },
  getEvidenceList: (params?: { kind?: string; scenario_ref?: string; variant_ref?: string; project_ref?: string; limit?: number }) => {
    const search = new URLSearchParams()
    for (const [key, value] of Object.entries(params ?? {})) if (value !== undefined) search.set(key, String(value))
    return request<Page<Evidence>>(`/evidence?${search}`)
  },
  getEvidence: (id: string) => request<Evidence>(`/evidence/${encodeURIComponent(id)}`),
  getSimulationEvidence: async (scenarioId: string, variantId: string | null, evidenceId: string | null): Promise<Evidence | null> => {
    if (!variantId) return null
    if (!evidenceId) return api.getLatestSimulation(scenarioId, variantId)
    const evidence = await api.getEvidence(evidenceId)
    if (evidence.kind !== 'evidence.simulation' || evidence.scenario_ref !== scenarioId || evidence.variant_ref !== variantId) {
      throw new Error('This simulation evidence does not belong to the selected scenario and variant. Select the latest result or correct the link.')
    }
    return evidence
  },
  getReadiness: (scenarioId: string, variantId: string) => request<{ status: string; errors: Array<{ message: string }>; warnings: Array<{ message: string }> }>(
    `/simulation/readiness?${new URLSearchParams({ scenario_id: scenarioId, variant_id: variantId })}`),
  runSimulation: (scenarioId: string, variantId: string, context: SimulationContext, credentials: Credentials) =>
    request<SimulationResponse>('/simulation/run', {
      method: 'POST',
      headers: credentials.keyId && credentials.apiKey ? { 'X-ScenarioDB-Key-Id': credentials.keyId, 'X-ScenarioDB-API-Key': credentials.apiKey } : {},
      body: JSON.stringify({ scenario_id: scenarioId, variant_id: variantId, execution_context: context,
        config: { include_timeline: true }, persist: false }),
    }),
}
