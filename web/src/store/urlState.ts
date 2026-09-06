import { useScenarioStore, type ActiveTab, type ViewLevel, type ViewMode } from './scenarioStore'

const fields = ['soc_id', 'project_id', 'scenario_id', 'variant_id', 'tab', 'level', 'mode', 'expand', 'sim', 'sim_evidence_id']
type State = ReturnType<typeof useScenarioStore.getState>

export function readScenarioUrl(href: string) {
  const params = new URL(href).searchParams
  const scenarioId = params.get('scenario_id') || null
  const variantId = scenarioId ? params.get('variant_id') || null : null
  const evidenceId = scenarioId && variantId ? params.get('sim_evidence_id') || null : null
  const tab = params.get('tab')
  const level = params.get('level')
  const mode = params.get('mode')
  return {
    socId: params.get('soc_id') || null,
    projectId: params.get('project_id') || null,
    scenarioId, variantId,
    activeTab: (tab && ['pipeline', 'timeline', 'evidence', 'explorer', 'query'].includes(tab) ? tab : 'timeline') as ActiveTab,
    viewLevel: (level && ['0', '1', '2'].includes(level) ? Number(level) : 0) as ViewLevel,
    viewMode: (mode && ['architecture', 'topology', 'resource'].includes(mode) ? mode : 'architecture') as ViewMode,
    expandTarget: params.get('expand') || null,
    simEvidenceId: evidenceId,
    simOverlayMode: evidenceId ? 'specific' as const : params.get('sim') === 'latest' ? 'latest' as const : 'none' as const,
    selectedTaskId: null,
  }
}

export function writeScenarioUrl(href: string, state: State): string {
  const url = new URL(href)
  fields.forEach(key => url.searchParams.delete(key))
  const values: Record<string, string | null> = {
    soc_id: state.socId, project_id: state.projectId, scenario_id: state.scenarioId,
    variant_id: state.scenarioId ? state.variantId : null,
    tab: state.activeTab === 'timeline' ? null : state.activeTab,
    level: state.viewLevel === 0 ? null : String(state.viewLevel),
    mode: state.viewMode === 'architecture' ? null : state.viewMode,
    expand: state.expandTarget,
    sim: state.simOverlayMode === 'latest' ? 'latest' : null,
    sim_evidence_id: state.scenarioId && state.variantId ? state.simEvidenceId : null,
  }
  for (const [key, value] of Object.entries(values)) if (value) url.searchParams.set(key, value)
  return url.href
}

// Install once before React renders. A popstate restores the whole hierarchy
// atomically, avoiding intermediate requests for mixed parent/child selections.
export function installScenarioUrlSync(browser: Window = window): () => void {
  let restoring = false
  const restore = () => {
    restoring = true
    try { useScenarioStore.setState(readScenarioUrl(browser.location.href)) }
    finally { restoring = false }
  }
  restore()
  const unsubscribe = useScenarioStore.subscribe(state => {
    if (restoring) return
    const next = writeScenarioUrl(browser.location.href, state)
    if (next !== browser.location.href) browser.history.pushState(null, '', next)
  })
  browser.addEventListener('popstate', restore)
  return () => { unsubscribe(); browser.removeEventListener('popstate', restore) }
}
