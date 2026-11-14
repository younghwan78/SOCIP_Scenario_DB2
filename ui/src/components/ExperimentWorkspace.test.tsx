// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import * as api from '../lib/api'
import { ExperimentWorkspaceBar, experimentTab, experimentTabHref, isExperimentPage, leverSummary, type LeverMeta } from './ExperimentWorkspace'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
afterEach(() => { vi.restoreAllMocks(); localStorage.clear() })

const LEVERS: LeverMeta[] = [
  { id: 'sw_growth', label: '차기 SW 증가', source: 'builtin', evaluation: 'timeline', explorable: true },
  { id: 'buffer_compression', label: 'Buffer 압축', source: 'builtin', evaluation: 'analytic', explorable: true },
  { id: 'fps', label: 'FPS', source: 'whatif', evaluation: 'resim', explorable: true },
  { id: 'dvfs_level', label: 'DVFS level', source: 'whatif', evaluation: 'resim', explorable: false },
]

it('says which levers each way of experimenting has', () => {
  expect(leverSummary(LEVERS)).toEqual({ builtin: ['차기 SW 증가', 'Buffer 압축'], whatif: 2, as_axes: ['FPS'] })
})

it('keeps only the context keys in the tab links and remembers the tab the nav item opens', () => {
  expect(experimentTabHref('explore', { project: 'p', scenario: 's', variant: 'v', experiment: undefined })).toBe('#/explore?project=p&scenario=s&variant=v')
  expect(isExperimentPage('cpu')).toBe(true)
  expect(isExperimentPage('timing')).toBe(false)
  expect(experimentTab('timing')).toBe('whatif') // nothing used yet
  expect(experimentTab('explore')).toBe('explore')
  expect(experimentTab('reports')).toBe('explore') // the last one used
})

it('shows the three tabs, the active question, the shared basis and the lever catalog', async () => {
  vi.spyOn(api, 'getJson').mockResolvedValue({ levers: LEVERS })
  const host = document.createElement('div')
  const root = createRoot(host)
  await act(async () => root.render(<ExperimentWorkspaceBar page="explore" project="p" scenario="s" variant="cam-v" />))
  const tabs = [...host.querySelectorAll('[role=tab]')]
  expect(tabs.map((t) => [t.textContent, t.getAttribute('aria-selected'), t.getAttribute('href')])).toEqual([
    ['한 조건 바꿔보기 · What-if', 'false', '#/whatif?project=p&scenario=s&variant=cam-v'],
    ['범위 탐색 · 조합 탐색', 'true', '#/explore?project=p&scenario=s&variant=cam-v'],
    ['CPU 배치 · CPU what-if', 'false', '#/cpu?project=p&scenario=s&variant=cam-v'],
  ])
  expect(host.textContent).toContain('범위 탐색 — SW · 압축 · DVFS')
  expect(host.textContent).toContain('기준: cam-v')
  expect(host.textContent).toContain('범위 탐색 내장 2개 (차기 SW 증가 · Buffer 압축) · 한 조건 바꿔보기 2개, 그중 1개는 범위 탐색의 레버 축으로도 사용 (FPS)')
  act(() => root.unmount())
})
