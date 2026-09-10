import type { Evidence, ViewResponse } from '../types'

const API_BASE = '/api/v1'
export interface Page<T> { items: T[]; total: number; limit: number; offset: number; has_next: boolean }
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

export type CatalogKind = 'soc-platforms' | 'projects' | 'scenarios' | 'variants'
export interface CatalogItem {
  id: string; name: string; category: string[]; project_ref?: string; soc_ref?: string
  board_type?: string; scenario_id?: string
}
export interface CatalogParams {
  soc_ref?: string; project_ref?: string; scenario_id?: string; board_type?: string
  id?: string; q?: string; offset?: number; limit?: number
  sort_by?: 'id' | 'name' | 'category'; sort_dir?: 'asc' | 'desc'
}

export const api = {
  getCatalog: (kind: CatalogKind, params: CatalogParams = {}, signal?: AbortSignal) => {
    const search = new URLSearchParams({ limit: '100', offset: '0' })
    for (const [key, value] of Object.entries(params)) if (value !== undefined) search.set(key, String(value))
    return request<Page<CatalogItem>>(`/catalog/${kind}?${search}`, { signal })
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
