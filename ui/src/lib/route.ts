// Hash router with shareable query context: #/pipeline?project=…&scenario=…&variant=…
import { useCallback, useEffect, useState } from 'react'
import { withReadSignal } from './readRequestScope'

export type Page = 'home' | 'explorer' | 'matrix' | 'pipeline' | 'behavior' | 'compare' | 'timing' | 'timing-fleet' | 'explore' | 'predictions' | 'reports' | 'calibration' | 'cpu' | 'whatif' | 'library' | 'settings'
export interface Route { page: Page; params: Record<string, string> }

const PAGES: Page[] = ['home', 'explorer', 'matrix', 'pipeline', 'behavior', 'compare', 'timing', 'timing-fleet', 'explore', 'predictions', 'reports', 'calibration', 'cpu', 'whatif', 'library', 'settings']

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
export const CONTEXT_KEYS = ['project', 'scenario', 'variant', 'experiment'] as const

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

const sameList = (a: unknown[] | undefined, b: unknown[] | undefined) =>
  !!a && !!b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]))

/** ``keep`` (U-08) = the identity of what is fetched (project, variant …) without refresh ticks. When the deps
 * change but ``keep`` is the same — a refresh of the same target — the previous data stays shown with
 * ``stale: true`` until the new result arrives. A different target still hides the old result at once, so a
 * value of another variant is never shown, not even for one render. */
export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[], opts?: { keep?: unknown[] }): { data: T | undefined; error: string | undefined; loading: boolean; stale?: boolean } {
  const pending = { data: undefined, error: undefined, loading: true }
  const keep = opts?.keep
  const [state, setState] = useState<{ data: T | undefined; error: string | undefined; loading: boolean; deps: unknown[]; keep?: unknown[] }>({ ...pending, deps, keep })
  useEffect(() => {
    let alive = true
    const controller = new AbortController()
    setState((prev) => (prev.data !== undefined && sameList(prev.keep, keep)
      ? { data: prev.data, error: undefined, loading: true, deps, keep }
      : { ...pending, deps, keep }))
    Promise.resolve().then(() => withReadSignal(controller.signal, () => fn(controller.signal))).then((data) => { if (alive) setState({ data, error: undefined, loading: false, deps, keep }) })
      .catch((e: unknown) => { if (alive) setState({ data: undefined, error: e instanceof Error ? e.message : String(e), loading: false, deps, keep }) })
    return () => { alive = false; controller.abort() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  if (sameList(deps, state.deps)) return state.loading && state.data !== undefined ? { ...state, stale: true } : state
  // Hide the old result during the render before the new effect runs as well, unless the target is the same.
  return state.data !== undefined && sameList(state.keep, keep) ? { ...state, loading: true, stale: true } : pending
}
