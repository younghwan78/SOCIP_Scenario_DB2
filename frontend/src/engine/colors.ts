// Slice color conventions ported 1:1 from dashboard/components/timing_chart.py
// so the interactive renderer keeps the exact visual language of the Plotly chart.
import type { TimelineEvent } from './types'

export const OTF_COLOR_FAMILIES: string[][] = [
  ['#2F6F68', '#3D8A82', '#75B2A8', '#B9D2CC'],
  ['#0F766E', '#14B8A6', '#2DD4BF', '#5EEAD4'],
  ['#7C3AED', '#8B5CF6', '#A78BFA', '#C4B5FD'],
  ['#059669', '#10B981', '#34D399', '#6EE7B7'],
  ['#0284C7', '#0EA5E9', '#38BDF8', '#7DD3FC'],
]
export const M2M_COLOR_FAMILIES = ['#D97706', '#EA580C', '#BE123C', '#A16207', '#C2410C']
export const SW_COLOR_FAMILIES = ['#9333EA', '#C026D3', '#DB2777', '#7E22CE']

export const SOURCE_COLOR = '#22C55E'
export const SINK_COLOR = '#0EA5E9'
export const DEFAULT_COLOR = '#64748B'

export function baseTaskId(taskId: unknown): string {
  return String(taskId ?? '').split('#f', 1)[0] ?? ''
}

export function baseOtfGroupId(groupId: unknown): string | null {
  if (!groupId) return null
  return String(groupId).split('#f', 1)[0] ?? null
}

export function timelineGroupIndex(value: string | null, fallback: string): number {
  const text = value || fallback
  let digits = ''
  for (const ch of text) {
    if (ch >= '0' && ch <= '9') digits += ch
  }
  if (digits) return parseInt(digits, 10)
  let sum = 0
  for (const ch of text) sum += ch.codePointAt(0) ?? 0
  return sum
}

export function sliceColor(event: TimelineEvent): string {
  const constraint = event.constraint_type
  if (constraint === 'source') return SOURCE_COLOR
  const taskType = String(event.task_type ?? '').toLowerCase()
  if (taskType.includes('sw')) {
    const index = timelineGroupIndex(String(event.resource_id || ''), baseTaskId(event.task_id))
    return SW_COLOR_FAMILIES[index % SW_COLOR_FAMILIES.length]
  }
  const edgeType = String(event.edge_type ?? '').toLowerCase()
  const otfGroup = baseOtfGroupId(event.otf_group_id)
  if (edgeType.includes('otf') || otfGroup) {
    const family = OTF_COLOR_FAMILIES[timelineGroupIndex(otfGroup, otfGroup ?? '') % OTF_COLOR_FAMILIES.length]
    const shadeIndex = timelineGroupIndex(null, baseTaskId(event.task_id)) % family.length
    return family[shadeIndex]
  }
  if (constraint === 'sink') return SINK_COLOR
  if (taskType.includes('dma') || taskType.includes('m2m')) {
    const index = timelineGroupIndex(String(event.resource_id || edgeType), baseTaskId(event.task_id))
    return M2M_COLOR_FAMILIES[index % M2M_COLOR_FAMILIES.length]
  }
  if (edgeType.includes('dma') || edgeType.includes('m2m')) {
    const index = timelineGroupIndex(String(event.resource_id || ''), baseTaskId(event.task_id))
    return M2M_COLOR_FAMILIES[index % M2M_COLOR_FAMILIES.length]
  }
  return DEFAULT_COLOR
}
