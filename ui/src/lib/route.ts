// Hash router with shareable query context: #/pipeline?project=…&scenario=…&variant=…
import { useCallback, useEffect, useState } from 'react'

export type Page = 'home' | 'explorer' | 'matrix' | 'pipeline' | 'compare' | 'timing' | 'timing-fleet' | 'explore' | 'predictions' | 'reports' | 'calibration' | 'library' | 'settings'
export interface Route { page: Page; params: Record<string, string> }

const PAGES: Page[] = ['home', 'explorer', 'matrix', 'pipeline', 'compare', 'timing', 'timing-fleet', 'explore', 'predictions', 'reports', 'calibration', 'library', 'settings']

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#\/?/, '')
  const [path, query = ''] = raw.split('?')
  // '#/' (brand link) and unknown paths land on Home
  const page = (PAGES as string[]).includes(path) ? (path as Page) : 'home'
  const params: Record<string, string> = {}
  new URLSearchParams(query).forEach((v, k) => { params[k] = v })
  return { page, params }
}

export function formatHash(route: Route): string {
  const q = new URLSearchParams(Object.entries(route.params).filter(([, v]) => v !== undefined && v !== ''))
  const s = q.toString()
  return `#/${route.page}${s ? `?${s}` : ''}`
}

/** Context keys carried across pages. */
export const CONTEXT_KEYS = ['project', 'scenario', 'variant'] as const

export type NavTarget = { page?: Page; params?: Record<string, string | undefined> }

/** A comparison belongs to one scenario; repeated picks must not duplicate columns. */
export function addComparison(currentScenario: string, currentIds: string, scenario: string, variant: string): string {
  const ids = currentScenario === scenario ? currentIds.split(',').filter(Boolean) : []
  return [...new Set([...ids, variant])].join(',')
}

export function useRoute(): [Route, (next: NavTarget, replace?: boolean) => void] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))
  useEffect(() => {
    const on = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const navigate = useCallback((next: NavTarget, replace = false) => {
    const cur = parseHash(window.location.hash)
    const page = next.page ?? cur.page
    // Context keys persist across pages; page-specific keys reset on page change.
    const base: Record<string, string> = {}
    for (const k of CONTEXT_KEYS) if (cur.params[k]) base[k] = cur.params[k]
    const carry = page === cur.page ? cur.params : base
    const params: Record<string, string> = { ...carry }
    for (const [k, v] of Object.entries(next.params ?? {})) {
      if (v === undefined || v === '') delete params[k]
      else params[k] = v
    }
    const hash = formatHash({ page, params })
    if (replace) window.history.replaceState(null, '', hash)
    else window.history.pushState(null, '', hash)
    setRoute({ page, params })
  }, [])
  return [route, navigate]
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): { data: T | undefined; error: string | undefined; loading: boolean } {
  const pending = { data: undefined, error: undefined, loading: true }
  const [state, setState] = useState<{ data: T | undefined; error: string | undefined; loading: boolean; deps: unknown[] }>({ ...pending, deps })
  useEffect(() => {
    let alive = true
    setState({ ...pending, deps })
    fn().then((data) => { if (alive) setState({ data, error: undefined, loading: false, deps }) })
      .catch((e: unknown) => { if (alive) setState({ data: undefined, error: e instanceof Error ? e.message : String(e), loading: false, deps }) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  // Hide the old result during the render before the new effect runs as well.
  return deps.length === state.deps.length && deps.every((v, i) => Object.is(v, state.deps[i])) ? state : pending
}
