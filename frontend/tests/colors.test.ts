import { describe, expect, it } from 'vitest'
import { baseOtfGroupId, baseTaskId, sliceColor, timelineGroupIndex } from '../src/engine/colors'
import type { TimelineEvent } from '../src/engine/types'

function event(partial: Partial<TimelineEvent>): TimelineEvent {
  return { task_id: 'task', start_ms: 0, end_ms: 1, duration_ms: 1, ...partial }
}

describe('color conventions (parity with timing_chart.py)', () => {
  it('strips frame suffix from task and group ids', () => {
    expect(baseTaskId('isp2#f1')).toBe('isp2')
    expect(baseTaskId('isp2')).toBe('isp2')
    expect(baseOtfGroupId('otf1#f2')).toBe('otf1')
    expect(baseOtfGroupId(null)).toBeNull()
  })

  it('derives group index from digits, else codepoint sum', () => {
    expect(timelineGroupIndex('DMA3', '')).toBe(3)
    expect(timelineGroupIndex(null, 'isp12')).toBe(12)
    expect(timelineGroupIndex('abc', '')).toBe(97 + 98 + 99)
  })

  it('colors source and sink like the Plotly chart', () => {
    expect(sliceColor(event({ constraint_type: 'source' }))).toBe('#22C55E')
    expect(sliceColor(event({ constraint_type: 'sink' }))).toBe('#0EA5E9')
  })

  it('colors SW tasks from the SW family by resource index', () => {
    expect(sliceColor(event({ task_type: 'sw', resource_id: 'CPU_L0' }))).toBe('#9333EA')
    expect(sliceColor(event({ task_type: 'sw', resource_id: 'CPU_1' }))).toBe('#C026D3')
  })

  it('colors OTF slices by group family and task shade', () => {
    const e = event({ task_id: 'isp2#f0', otf_group_id: 'otf1#f0', edge_type: 'OTF' })
    // family index 1 -> ['#0F766E', ...]; shade from base task 'isp2' -> index 2
    expect(sliceColor(e)).toBe('#2DD4BF')
  })

  it('colors DMA/M2M slices from the M2M family', () => {
    expect(sliceColor(event({ task_type: 'dma', resource_id: 'DMA3', task_id: 'copy#f1' }))).toBe('#A16207')
    expect(sliceColor(event({ edge_type: 'M2M', resource_id: 'DMA0' }))).toBe('#D97706')
  })

  it('falls back to the neutral slate color', () => {
    expect(sliceColor(event({}))).toBe('#64748B')
  })
})
