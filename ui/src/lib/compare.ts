// Cross-project / cross-scenario comparison helpers (pure, unit-tested).
import type { CatalogItem, Dict, VariantDetail, ViewResponse } from './api'
import { shortLabels } from './conditions'
import { pipelineIdOf } from './graph'
import { canonicalOf, projectTag, type CompareItem, type ProjectInfo } from './projects'

export interface ItemLabel { key: string; short: string; full: string; project?: string; scenario?: string }

/** Column labels: add a 과제 tag / scenario name only when the set spans several of them. */
export function itemLabels(items: CompareItem[], catalog: CatalogItem[], projects: ProjectInfo[]): ItemLabel[] {
  const cat = items.map((i) => catalog.find((c) => c.scenario_id === i.scenario))
  const multiProject = new Set(cat.map((c) => c?.project_id)).size > 1
  const multiScenario = new Set(cat.map((c) => (c ? canonicalOf(c) : undefined))).size > 1
  const vShort = shortLabels([...new Set(items.map((i) => i.variant))])
  return items.map((it, n) => {
    const c = cat[n]
    const p = projects.find((x) => x.id === c?.project_id)
    const project = multiProject ? projectTag(p, projects) : undefined
    const scenario = multiScenario ? c?.scenario_name ?? it.scenario : undefined
    const short = [project, scenario, vShort[it.variant] ?? it.variant].filter(Boolean).join(' · ')
    return { key: `${it.scenario}~${it.variant}`, short, full: `${p ? `${p.soc} ${p.board} · ` : ''}${c?.scenario_name ?? it.scenario} · ${it.variant}`, project, scenario }
  })
}

/** Strip the 'ip-' prefix and the SoC tag suffix so the same IP compares equal across 과제. */
export function ipShort(ref: string | null | undefined): string {
  return String(ref ?? '').replace(/^ip-/, '').replace(/-(s5e\d{4}|exynos\w+)$/i, '')
}

/** Active pipeline node → IP (from the Level-1 view). */
export function nodeIps(view: ViewResponse | undefined | null): Map<string, string> {
  const out = new Map<string, string>()
  for (const { data } of view?.nodes ?? []) {
    if (!data.ip_ref || data.type === 'group' || data.type === 'sw') continue
    out.set(pipelineIdOf(data.id), ipShort(data.ip_ref))
  }
  return out
}

/** Node processing size (node_configs.<node>.sim width × height). */
export function nodeSizes(detail: VariantDetail | undefined | null): Map<string, string> {
  const out = new Map<string, string>()
  for (const [node, cfg] of Object.entries(detail?.node_configs ?? {})) {
    const sim = (cfg as Dict)?.sim as Dict | undefined
    if (sim && typeof sim.width === 'number' && typeof sim.height === 'number') out.set(node, `${sim.width}×${sim.height}`)
  }
  return out
}

export const pixels = (s: string | undefined | null): number | null => {
  const m = String(s ?? '').match(/(\d+)\s*[x×]\s*(\d+)/)
  return m ? Number(m[1]) * Number(m[2]) : null
}

export interface Insight {
  index: number
  kpi: { label: string; unit: string; ref: number; value: number; pct: number }[]
  dmaTotal?: { ref: number; value: number; pct: number }
  topIp: { ip: string; delta: number }[]
  changed: { conditions: number; ips: number; sizes: number }
}

/** Per non-reference item: KPI Δ, DMA Δ and the IPs that moved most (vs item 0). */
export function insights(args: {
  n: number
  kpi: { label: string; unit: string; values: (number | null)[] }[]
  dma: (number | null)[]
  traffic: (Map<string, number> | null)[]
  changedConditions: number[]
  ipMaps: Map<string, string>[]
  sizeMaps: Map<string, string>[]
}): Insight[] {
  const out: Insight[] = []
  const pct = (v: number, r: number) => (r ? ((v - r) / r) * 100 : 0)
  const diffCount = (maps: Map<string, string>[], i: number) => {
    const keys = new Set([...(maps[0]?.keys() ?? []), ...(maps[i]?.keys() ?? [])])
    return [...keys].filter((k) => maps[0]?.get(k) !== maps[i]?.get(k)).length
  }
  for (let i = 1; i < args.n; i++) {
    const kpi = args.kpi.flatMap((r) => {
      const ref = r.values[0], v = r.values[i]
      return ref !== null && v !== null ? [{ label: r.label, unit: r.unit, ref, value: v, pct: pct(v, ref) }] : []
    })
    const d0 = args.dma[0], di = args.dma[i]
    const t0 = args.traffic[0], ti = args.traffic[i]
    const topIp = t0 && ti ? [...new Set([...t0.keys(), ...ti.keys()])]
      .map((ip) => ({ ip, delta: +((ti.get(ip) ?? 0) - (t0.get(ip) ?? 0)).toFixed(1) }))
      .filter((x) => Math.abs(x.delta) >= 0.5).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 4) : []
    out.push({
      index: i, kpi,
      dmaTotal: d0 !== null && di !== null && d0 !== undefined && di !== undefined ? { ref: d0, value: di, pct: pct(di, d0) } : undefined,
      topIp,
      changed: { conditions: args.changedConditions[i] ?? 0, ips: diffCount(args.ipMaps, i), sizes: diffCount(args.sizeMaps, i) },
    })
  }
  return out
}
