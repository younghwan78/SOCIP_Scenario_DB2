/** Design space of an exploration run (API ≥ 2026-11-12, `sdb.designspace/1`): lever axes + constraints + objective. */
export interface LeverAxis { lever: string; values: unknown[]; params?: Record<string, unknown>; label?: string | null }
export interface DesignSpace {
  schema_version: string; axes: LeverAxis[]
  constraints?: Record<string, unknown>; objective?: Record<string, unknown>; evaluation?: Record<string, unknown>
}

const LABEL: Record<string, string> = {
  sw_statistic: 'SW 통계', sw_growth: 'SW 증가', eis: 'EIS', dvfs_headroom: 'DVFS headroom',
  buffer_compression: 'Buffer 압축', power_options: 'Power option',
}
const OPTION_KIND: Record<string, string> = { knob: 'arch knob', ip_mode: 'IP mode' }
const list = (values: unknown[], each: (v: unknown) => string = String) => values.map(each).join(' · ')

/** One axis as visible text: what is explored, or that the lever is held (`explored: false`). */
export function axisSummary(axis: LeverAxis): { label: string; text: string; explored: boolean } {
  const label = axis.label || LABEL[axis.lever] || axis.lever
  const p = axis.params ?? {}
  const off = p.enabled === false || !axis.values.length
  switch (axis.lever) {
    case 'sw_statistic': return { label, text: list(axis.values), explored: axis.values.length > 1 }
    case 'sw_growth': return { label, text: list(axis.values, (v) => `×${Number(v).toFixed(1)}`), explored: axis.values.length > 1 }
    case 'eis': return { label, text: list(axis.values), explored: false }
    case 'dvfs_headroom': {
      const steps = Math.max(0, axis.values.length - 1)
      return { label, text: steps ? `+0 ~ +${steps} level` : '올리지 않음', explored: steps > 0 }
    }
    case 'buffer_compression':
      return off ? { label, text: '탐색 안 함', explored: false }
        : { label, text: `${list(axis.values)}${p.max_buffers != null ? ` (buffer ≤ ${p.max_buffers})` : ''}`, explored: true }
    case 'power_options':
      return off ? { label, text: '탐색 안 함', explored: false }
        : { label, text: `${list(axis.values, (v) => OPTION_KIND[String(v)] ?? String(v))}${p.max_sets != null ? ` (조합 ≤ ${p.max_sets})` : ''}`, explored: true }
    default: return { label, text: `${axis.values.length}개 값`, explored: axis.values.length > 1 }
  }
}
