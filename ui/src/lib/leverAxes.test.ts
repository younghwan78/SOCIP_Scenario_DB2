// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { clearPendingLevers, leverAxesError, leverSetCount, readPendingLevers, savePendingLevers, toLeverAxis } from './leverAxes'
import { DEFAULT_RUN, runBody } from './archExplore'
import { companionPresets, conditionSummary } from '../components/ConcurrentCard'
import type { WhatIfChange } from './scenarioWhatIf'

describe('lever axes for a range exploration (X-07)', () => {
  const fps = [{ target: 'fps', value: 24 }, { target: 'fps', value: 60 }] as WhatIfChange[]
  const size = [{ target: 'output_size', anchor_id: 'preview', width: 1920, height: 1080 }, { target: 'output_size', anchor_id: 'preview', width: 3840, height: 2160 }] as WhatIfChange[]
  it('moves the selector to params and keeps the change fields as values', () => {
    expect(toLeverAxis('FPS', fps)).toEqual({ lever: 'fps', label: 'FPS', params: {}, values: [{ value: 24 }, { value: 60 }] })
    expect(toLeverAxis('출력 크기 · preview', size)).toEqual({ lever: 'output_size', label: '출력 크기 · preview', params: { anchor_id: 'preview' },
      values: [{ width: 1920, height: 1080 }, { width: 3840, height: 2160 }] })
  })
  it('counts combinations like the server and enforces its caps', () => {
    const axes = [toLeverAxis('FPS', fps), toLeverAxis('size', size)]
    expect(leverSetCount(axes, 'exhaustive')).toBe(8)   // (2 + 1) × (2 + 1) − 1
    expect(leverSetCount(axes, 'screen')).toBe(4)
    expect(leverAxesError(axes, 'exhaustive', 4)).toContain('조합 8개 > 상한 4')
    expect(leverAxesError(axes, 'screen', 4)).toBeNull()
    // a kind the catalog does not flag explorable is refused before the run
    expect(leverAxesError(axes, 'screen', 4, new Set(['fps']))).toContain('범위 탐색 축으로 쓸 수 없는 레버: size')
    expect(toLeverAxis('x'.repeat(200), fps).label?.length).toBe(120)
  })
  it('keeps pending axes per project', () => {
    savePendingLevers({ project_ref: 'p1', scenario_id: 's', variant_id: 'v', at: 't', axes: [toLeverAxis('FPS', fps)] })
    expect(readPendingLevers('p1')?.axes).toHaveLength(1)
    expect(readPendingLevers('p2')).toBeNull()
    clearPendingLevers()
    expect(readPendingLevers('p1')).toBeNull()
  })
  it('puts the axes into the run spec only when there are some', () => {
    const plain = runBody(['s'], '', 't', DEFAULT_RUN)
    expect('levers' in plain.spec.axes).toBe(false)
    const withLevers = runBody(['s'], '', 't', { ...DEFAULT_RUN, levers: [toLeverAxis('FPS', fps)], lever_search: 'screen', lever_max_sets: 32 })
    expect(withLevers.spec.axes).toMatchObject({ levers: [{ lever: 'fps' }], lever_search: 'screen', lever_max_sets: 32 })
  })
})

describe('concurrent picker (X-14)', () => {
  it('summarises conditions and offers companions by scenario id', () => {
    expect(conditionSummary({ resolution: 'UHD', fps: 30, codec: { a: 1 }, hdr: 'HDR10', extra: 1 })).toBe('resolution UHD · fps 30 · hdr HDR10')
    const catalog = [
      { scenario_id: 'uc-call-voice-e2600', scenario_name: 'Voice Call', default_variant_id: 'voice-call-volte' },
      { scenario_id: 'uc-cam-recording-e2600', scenario_name: 'Camera Recording', default_variant_id: 'cam-rec-uhd30' },
      { scenario_id: 'uc-cam-recording-apv-e2600', scenario_name: 'Camera Recording APV', default_variant_id: 'apv' },
    ]
    const p = companionPresets(catalog, 'uc-cam-recording-e2600')
    expect(p.map((x) => x.label)).toEqual(['음성 통화'])
    expect(p[0].member).toEqual({ scenario_id: 'uc-call-voice-e2600', variant_id: 'voice-call-volte' })
  })
})
