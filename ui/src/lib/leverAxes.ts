import type { LeverAxis } from './designSpace'
import type { WhatIfChange } from './scenarioWhatIf'

/** X-07: re-simulation lever axes for a range exploration, built from the What-if value-range axes.
 * The exploration API takes ``{lever, values, params}`` (sim/arch_exploration.py LeverAxis): ``lever`` = the
 * What-if change kind, ``params`` = its selector (node / stream / buffer …), each value = the change fields
 * without the target and the selector (api/services/design_axes.py _value_fields takes a dict as is). */
const SELECTORS = ['anchor_id', 'node_id', 'stream_id', 'buffer_id', 'domain', 'param'] as const

export function toLeverAxis(label: string, values: WhatIfChange[]): LeverAxis {
  const first = values[0]
  const params: Record<string, unknown> = {}
  for (const k of SELECTORS) if (first?.[k] != null) params[k] = first[k]
  return {
    lever: String(first?.target ?? ''), label, params,
    values: values.map((v) => Object.fromEntries(Object.entries(v).filter(([k, x]) => k !== 'target' && !(SELECTORS as readonly string[]).includes(k) && x != null))),
  }
}

/** Combinations the server re-simulates: every axis also keeps its current value; "screen" tries each value alone. */
export function leverSetCount(axes: LeverAxis[], search: 'exhaustive' | 'screen'): number {
  if (!axes.length) return 0
  return search === 'screen' ? axes.reduce((n, a) => n + a.values.length, 0) : axes.reduce((n, a) => n * (a.values.length + 1), 1) - 1
}

/** The server's caps (ExplorationAxes._levers): at most 8 axes, 16 values each, sets ≤ lever_max_sets (≤ 256). */
export function leverAxesError(axes: LeverAxis[], search: 'exhaustive' | 'screen', maxSets: number): string | null {
  if (axes.length > 8) return '레버 축은 8개까지입니다.'
  if (axes.some((a) => !a.values.length || a.values.length > 16)) return '레버 축마다 값 1–16개.'
  const n = leverSetCount(axes, search)
  if (n > maxSets) return search === 'screen' ? `값 ${n}개 > 상한 ${maxSets} — 값을 줄이세요.` : `조합 ${n}개 > 상한 ${maxSets} — 값을 줄이거나 screen으로.`
  return null
}

/** Hand-over from What-if (one variant's value-range axes) to the exploration form. Browser storage only:
 * a convenience, never required (the form works without it). */
const KEY = 'explore.pendingLevers'
export interface PendingLevers { scenario_id: string; variant_id: string; axes: LeverAxis[]; at: string }
export function savePendingLevers(p: PendingLevers): void {
  try { window.localStorage.setItem(KEY, JSON.stringify(p)) } catch { /* storage unavailable */ }
}
export function readPendingLevers(): PendingLevers | null {
  try { const raw = window.localStorage.getItem(KEY); return raw ? (JSON.parse(raw) as PendingLevers) : null } catch { return null }
}
export function clearPendingLevers(): void {
  try { window.localStorage.removeItem(KEY) } catch { /* storage unavailable */ }
}
