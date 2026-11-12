// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { DesignSpaceSummary } from './DesignSpaceSummary'
import { axisSummary, type DesignSpace } from '../lib/designSpace'

const space: DesignSpace = {
  schema_version: 'sdb.designspace/1',
  axes: [
    { lever: 'sw_statistic', values: ['mean', 'max'] },
    { lever: 'sw_growth', values: [1, 1.1, 1.2] },
    { lever: 'eis', values: ['auto'] },
    { lever: 'dvfs_headroom', values: [0, 1] },
    { lever: 'buffer_compression', values: ['lossless', 'lossy'], params: { max_buffers: 8 } },
    { lever: 'power_options', values: ['knob', 'ip_mode'], params: { max_sets: 64, enabled: false } },
  ],
}

it('shows every axis of the run as text and mutes the levers that are held', () => {
  const host = document.createElement('div')
  const root = createRoot(host)
  act(() => root.render(<DesignSpaceSummary space={space} />))
  const chips = [...host.querySelectorAll('.chip')]
  expect(chips.map((c) => c.textContent)).toEqual([
    'SW 통계 mean · max', 'SW 증가 ×1.0 · ×1.1 · ×1.2', 'EIS auto', 'DVFS headroom +0 ~ +1 level',
    'Buffer 압축 lossless · lossy (buffer ≤ 8)', 'Power option 탐색 안 함'])
  expect(chips.map((c) => c.classList.contains('ds-held'))).toEqual([false, false, true, false, false, true])
  expect(host.querySelector('[aria-label="탐색 공간"]')).not.toBeNull()
  act(() => root.unmount())
})

it('renders nothing for a run without a design space (older API or a spec that no longer validates)', () => {
  const host = document.createElement('div')
  const root = createRoot(host)
  act(() => root.render(<DesignSpaceSummary space={null} />))
  expect(host.innerHTML).toBe('')
  act(() => root.unmount())
})

it('adds the objective SW point the engine always evaluates', () => {
  const ctx = { objective: { statistic: 'max', runtime_scale: 1 } }
  expect(axisSummary({ lever: 'sw_statistic', values: ['mean'] }, ctx)).toEqual({ label: 'SW 통계', text: 'mean · max', explored: true })
  expect(axisSummary({ lever: 'sw_growth', values: [1.2] }, ctx)).toEqual({ label: 'SW 증가', text: '×1.0 · ×1.2', explored: true })
  // already listed: nothing is added, and one value is a held lever
  expect(axisSummary({ lever: 'sw_statistic', values: ['max'] }, ctx).explored).toBe(false)
  expect(axisSummary({ lever: 'sw_growth', values: [1] }, ctx)).toEqual({ label: 'SW 증가', text: '×1.0', explored: false })
})

it('keeps the digits of a growth factor', () => {
  expect(axisSummary({ lever: 'sw_growth', values: [1, 1.04, 1.05, 1.25] }).text).toBe('×1.0 · ×1.04 · ×1.05 · ×1.25')
  expect(axisSummary({ lever: 'sw_growth', values: [0.1 + 0.2, 2] }).text).toBe('×0.3 · ×2.0')
})

it('shows the compression modes the constraints leave', () => {
  const noLossy = { constraints: { allow_lossy: false } }
  expect(axisSummary({ lever: 'buffer_compression', values: ['lossless', 'lossy'], params: { max_buffers: 8 } }, noLossy).text).toBe('lossless (buffer ≤ 8)')
  expect(axisSummary({ lever: 'buffer_compression', values: ['lossy'] }, noLossy)).toEqual({ label: 'Buffer 압축', text: '탐색 안 함', explored: false })
  expect(axisSummary({ lever: 'buffer_compression', values: ['lossy'] }, { constraints: { allow_lossy: true } }).text).toBe('lossy')
  expect(axisSummary({ lever: 'buffer_compression', values: ['lossless'], params: { max_buffers: 0 } }).explored).toBe(false)
})

it('summarises single values, no DVFS raise and levers it does not know', () => {
  expect(axisSummary({ lever: 'sw_growth', values: [1.2] })).toEqual({ label: 'SW 증가', text: '×1.2', explored: false })
  expect(axisSummary({ lever: 'dvfs_headroom', values: [0] })).toEqual({ label: 'DVFS headroom', text: '올리지 않음', explored: false })
  expect(axisSummary({ lever: 'power_options', values: ['ip_mode'], params: { max_sets: 16 } }).text).toBe('IP mode (조합 ≤ 16)')
  expect(axisSummary({ lever: 'chain_size', values: [{}, {}], label: 'MCSC 출력' })).toEqual({ label: 'MCSC 출력', text: '2개 값', explored: true })
})
