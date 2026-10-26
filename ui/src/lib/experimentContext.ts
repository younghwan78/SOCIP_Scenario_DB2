import { useEffect, useState } from 'react'
import { credentialKeyId, useCredentialKeyId } from './auth'
import type { Page } from './route'
import type { WhatIfChange, WhatIfCoverage, WhatIfMetrics, WhatIfScope } from './scenarioWhatIf'

export interface ExperimentCandidate {
  id: string; title: string; condition_hash: string; baseline_hash: string; analysis_hash?: string
  changes: WhatIfChange[]; metrics: WhatIfMetrics; baseline_metrics: WhatIfMetrics
  coverage: WhatIfCoverage; iq_required: string[]; created_at: string; saved_experiment_id?: string
  config?: Record<string, unknown>; options?: Record<string, unknown>; basis_ref?: string; comparison?: 'retune' | 'fixed_opp'
}
export interface ExperimentContext {
  scope: WhatIfScope; baseline_hash?: string; analysis_hash?: string; basis_label?: string; changes: WhatIfChange[]
  config?: Record<string, unknown>; options?: Record<string, unknown>; basis_ref?: string; comparison?: 'retune' | 'fixed_opp'
  candidates: ExperimentCandidate[]; active_candidate_id?: string; updated_at: string
  job_id?: string
}
const VERSION = 1, MAX_SCOPES = 10, MAX_CANDIDATES = 5, MAX_BYTES = 160_000
const EVENT = 'scenariodb-experiment-context'
const storageKey = () => `scenariodb.experiment.v${VERSION}:${credentialKeyId() ? `key:${encodeURIComponent(credentialKeyId())}` : 'anonymous'}`
const scopeKey = (scope: WhatIfScope) => JSON.stringify([scope.project_ref, scope.scenario_id, scope.variant_id])
const isScope = (value: unknown): value is WhatIfScope => !!value && typeof value === 'object' && ['project_ref', 'scenario_id', 'variant_id'].every((key) => typeof (value as Record<string, unknown>)[key] === 'string')
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((entry) => typeof entry === 'string')
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const changes = (value: unknown): value is WhatIfChange[] => Array.isArray(value) && value.length <= 8 && value.every((change) => record(change) && typeof change.target === 'string')
const metrics = (value: unknown): value is WhatIfMetrics => record(value) && ['modeled_power_mw', 'cpu_power_mw', 'ip_power_mw', 'memory_power_mw', 'bw_mbs', 'fps', 'period_ms'].every((key) => typeof value[key] === 'number' && Number.isFinite(value[key])) && typeof value.feasible === 'boolean'
const coverage = (value: unknown): value is WhatIfCoverage => record(value) && typeof value.complete === 'boolean' && typeof value.scope === 'string' && strings(value.missing_components) && strings(value.excluded_components) && strings(value.assumptions)
const candidate = (value: unknown): value is ExperimentCandidate => record(value) && ['id', 'title', 'condition_hash', 'baseline_hash', 'created_at'].every((key) => typeof value[key] === 'string') && changes(value.changes) && metrics(value.metrics) && metrics(value.baseline_metrics) && coverage(value.coverage) && strings(value.iq_required)
/** Only small, scoped browser drafts are retained. Server records remain the source of truth. */
export function listExperimentContexts(): ExperimentContext[] {
  try {
    const raw = sessionStorage.getItem(storageKey())
    if (!raw || raw.length > MAX_BYTES) return []
    const doc = JSON.parse(raw)
    if (doc.version !== VERSION || !Array.isArray(doc.items)) return []
    return doc.items.filter((item: ExperimentContext) => isScope(item?.scope) && changes(item.changes) && Array.isArray(item.candidates) && typeof item.updated_at === 'string')
      .slice(0, MAX_SCOPES).map((item: ExperimentContext) => ({ ...item, config: record(item.config) ? item.config : undefined, options: record(item.options) ? item.options : undefined, basis_ref: typeof item.basis_ref === 'string' ? item.basis_ref : undefined, candidates: item.candidates.filter(candidate).slice(0, MAX_CANDIDATES) }))
  } catch { return [] }
}
export const readExperimentContext = (scope: WhatIfScope): ExperimentContext | undefined => listExperimentContexts().find((item) => scopeKey(item.scope) === scopeKey(scope))
export function updateExperimentContext(scope: WhatIfScope, patch: Partial<Omit<ExperimentContext, 'scope' | 'updated_at'>>): ExperimentContext {
  const items = listExperimentContexts(), previous = items.find((item) => scopeKey(item.scope) === scopeKey(scope))
  const next: ExperimentContext = { changes: [], candidates: [], ...previous, ...patch, scope, updated_at: new Date().toISOString() }
  next.changes = next.changes.slice(0, 8)
  next.candidates = next.candidates.slice(0, MAX_CANDIDATES)
  const document = { version: VERSION, items: [next, ...items.filter((item) => scopeKey(item.scope) !== scopeKey(scope))].slice(0, MAX_SCOPES) }
  try {
    let raw = JSON.stringify(document)
    while (raw.length > MAX_BYTES && document.items.length > 1) { document.items.pop(); raw = JSON.stringify(document) }
    if (raw.length <= MAX_BYTES) sessionStorage.setItem(storageKey(), raw)
  } catch { /* Storage can be disabled; calculations and server saves still work. */ }
  window.dispatchEvent(new Event(EVENT))
  return next
}
export function useExperimentContext(scope: WhatIfScope): ExperimentContext | undefined {
  const principal = useCredentialKeyId(), key = scopeKey(scope)
  const [state, setState] = useState(() => ({ key, principal, value: readExperimentContext(scope) }))
  useEffect(() => {
    const update = () => setState({ key, principal, value: readExperimentContext(scope) })
    update(); window.addEventListener(EVENT, update); window.addEventListener('storage', update)
    return () => { window.removeEventListener(EVENT, update); window.removeEventListener('storage', update) }
  }, [key, principal])
  return state.key === key && state.principal === principal ? state.value : readExperimentContext(scope)
}
export function experimentHref(page: Page, scope: WhatIfScope, experimentId?: string): string {
  const params = new URLSearchParams({ project: scope.project_ref, scenario: scope.scenario_id, variant: scope.variant_id })
  if (experimentId) params.set('experiment', experimentId)
  return `#/${page}?${params}`
}
