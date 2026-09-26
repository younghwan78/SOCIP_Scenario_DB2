// Project (SoC 과제) scoping and cross-project scenario matching.
import type { CatalogItem } from './api'

export interface ProjectInfo {
  id: string
  soc: string
  board: string
  name: string
  scenarios: number
  variants: number
}

export const socLabel = (s?: string | null) => (s ?? '').replace(/^soc-/, '').replace(/^exynos/i, 'Exynos') || 'SoC 미정'
export const projLabel = (p: string) => p.replace(/^proj-/, '').toUpperCase()

/** Cross-project join key: metadata.canonical_usecase, else the scenario id. */
export const canonicalOf = (c: Pick<CatalogItem, 'scenario_id' | 'canonical_usecase'>): string => c.canonical_usecase || c.scenario_id

export function projectsOf(catalog: CatalogItem[]): ProjectInfo[] {
  const m = new Map<string, ProjectInfo>()
  for (const c of catalog) {
    const p = m.get(c.project_id) ?? { id: c.project_id, soc: socLabel(c.soc_ref), board: c.board_type ?? projLabel(c.project_id), name: c.project_name ?? '', scenarios: 0, variants: 0 }
    p.scenarios += 1
    p.variants += c.variant_count
    m.set(c.project_id, p)
  }
  return [...m.values()].sort((a, b) => a.soc.localeCompare(b.soc, undefined, { numeric: true }) || a.id.localeCompare(b.id))
}

export const projectText = (p: ProjectInfo | undefined) => (p ? `${p.soc} · ${p.board}` : '')

/** Short tag distinguishing projects in labels (e.g. "2700·E2700-REF" → "2700"). */
export function projectTag(p: ProjectInfo | undefined, all: ProjectInfo[]): string {
  if (!p) return '?'
  const num = p.soc.match(/\d{3,}/)?.[0]
  const sameSoc = all.filter((x) => x.soc === p.soc).length > 1
  return num && !sameSoc ? num : `${num ?? p.soc}/${p.board}`
}

/** Scenario of `project` matching the canonical use case of `from` (same scenario in another 과제). */
export function counterpart(catalog: CatalogItem[], from: CatalogItem | undefined, project: string): CatalogItem | undefined {
  const inProject = catalog.filter((c) => c.project_id === project)
  if (!from) return undefined
  return inProject.find((c) => canonicalOf(c) === canonicalOf(from)) ?? inProject.find((c) => c.scenario_name === from.scenario_name)
}

export const DEFAULT_CANONICAL = 'uc-camera-recording'

/** Default scenario inside a project: camera recording if present, else the first. */
export function defaultScenario(scoped: CatalogItem[]): CatalogItem | undefined {
  return scoped.find((c) => canonicalOf(c) === DEFAULT_CANONICAL) ?? scoped.find((c) => c.scenario_name === 'Camera Recording') ?? scoped[0]
}

// ---- comparison set: ordered (scenario, variant) pairs, first = reference ----
export interface CompareItem { scenario: string; variant: string }
const SEP = '~'

export function parseItems(raw: string | undefined): CompareItem[] {
  const out: CompareItem[] = []
  for (const tok of (raw ?? '').split(',').filter(Boolean)) {
    const i = tok.indexOf(SEP)
    if (i <= 0) continue
    const it = { scenario: tok.slice(0, i), variant: tok.slice(i + 1) }
    if (it.variant && !out.some((o) => o.scenario === it.scenario && o.variant === it.variant)) out.push(it)
  }
  return out
}

export const formatItems = (items: CompareItem[]) => items.map((i) => `${i.scenario}${SEP}${i.variant}`).join(',')

/** Legacy `scenario` + `variants=a,b` URLs map onto items. */
export function compareItems(params: Record<string, string>, scenario: string, variant: string): CompareItem[] {
  const items = parseItems(params.items)
  if (items.length) return items
  const ids = (params.variants ?? variant).split(',').filter(Boolean)
  return [...new Set(ids)].map((v) => ({ scenario, variant: v }))
}

export function addItem(items: CompareItem[], add: CompareItem): CompareItem[] {
  return items.some((i) => i.scenario === add.scenario && i.variant === add.variant) ? items : [...items, add]
}
