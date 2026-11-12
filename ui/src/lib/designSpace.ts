/** Design space of an exploration run (API ≥ 2026-11-12, `sdb.designspace/1`): lever axes + constraints + objective. */
export interface LeverAxis { lever: string; values: unknown[]; params?: Record<string, unknown>; label?: string | null }
export interface DesignSpace {
  schema_version: string; axes: LeverAxis[]
  constraints?: Record<string, unknown>; objective?: Record<string, unknown>; evaluation?: Record<string, unknown>
}
type Context = Pick<DesignSpace, 'constraints' | 'objective'>

const LABEL: Record<string, string> = {
  sw_statistic: 'SW 통계', sw_growth: 'SW 증가', eis: 'EIS', dvfs_headroom: 'DVFS headroom',
  buffer_compression: 'Buffer 압축', power_options: 'Power option',
}
const OPTION_KIND: Record<string, string> = { knob: 'arch knob', ip_mode: 'IP mode' }
const list = (values: unknown[], each: (v: unknown) => string = String) => values.map(each).join(' · ')
/** ×1.0, ×1.2, ×1.05: one decimal at least, and every digit the request carried (1.04 is not ×1.0). */
export const scaleText = (v: unknown) => {
  const n = Number(v)
  return `×${Number.isInteger(n) ? n.toFixed(1) : String(Number(n.toPrecision(6)))}`
}

/** One axis as visible text: what the engine evaluates, or that the lever is held (`explored: false`).
 * `space` gives the rules the engine applies on top of the listed values: the objective's SW statistic and
 * growth are always evaluated too, and `allow_lossy: false` removes the lossy compression mode. */
export function axisSummary(axis: LeverAxis, space?: Context): { label: string; text: string; explored: boolean } {
  const label = axis.label || LABEL[axis.lever] || axis.lever
  const p = axis.params ?? {}
  const objective = space?.objective ?? {}
  switch (axis.lever) {
    case 'sw_statistic': {
      const stats = objective.statistic == null || axis.values.includes(objective.statistic) ? axis.values : [...axis.values, objective.statistic]
      return { label, text: list(stats), explored: stats.length > 1 }
    }
    case 'sw_growth': {
      const own = Number(objective.runtime_scale)
      const scales = [...new Set([...axis.values.map(Number), ...(Number.isFinite(own) && own > 0 ? [own] : [])])].sort((a, b) => a - b)
      return { label, text: list(scales, scaleText), explored: scales.length > 1 }
    }
    case 'eis': return { label, text: list(axis.values), explored: false }
    case 'dvfs_headroom': {
      const steps = Math.max(0, axis.values.length - 1)
      return { label, text: steps ? `+0 ~ +${steps} level` : '올리지 않음', explored: steps > 0 }
    }
    case 'buffer_compression': {
      const modes = space?.constraints?.allow_lossy === false ? axis.values.filter((m) => m !== 'lossy') : axis.values
      return p.enabled === false || !modes.length || p.max_buffers === 0 ? { label, text: '탐색 안 함', explored: false }
        : { label, text: `${list(modes)}${p.max_buffers != null ? ` (buffer ≤ ${p.max_buffers})` : ''}`, explored: true }
    }
    case 'power_options':
      return p.enabled === false || !axis.values.length ? { label, text: '탐색 안 함', explored: false }
        : { label, text: `${list(axis.values, (v) => OPTION_KIND[String(v)] ?? String(v))}${p.max_sets != null ? ` (조합 ≤ ${p.max_sets})` : ''}`, explored: true }
    default: return { label, text: `${axis.values.length}개 값`, explored: axis.values.length > 1 }
  }
}
