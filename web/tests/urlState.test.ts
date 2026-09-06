import { expect, it, vi } from 'vitest'
import { useScenarioStore } from '../src/store/scenarioStore'
import { installScenarioUrlSync, readScenarioUrl, writeScenarioUrl } from '../src/store/urlState'

it('restores and round-trips hierarchy, drilldown and pinned evidence', () => {
  const href = 'http://localhost/?soc_id=soc-a&project_id=board-a&scenario_id=camera&variant_id=UHD%2060&tab=pipeline&level=2&expand=video&sim_evidence_id=sim-a&note=keep'
  useScenarioStore.setState(readScenarioUrl(href))
  expect(useScenarioStore.getState()).toMatchObject({ socId: 'soc-a', projectId: 'board-a', scenarioId: 'camera', variantId: 'UHD 60', activeTab: 'pipeline', viewLevel: 2, expandTarget: 'video', simEvidenceId: 'sim-a', simOverlayMode: 'specific' })
  expect(readScenarioUrl(writeScenarioUrl(href, useScenarioStore.getState()))).toEqual(readScenarioUrl(href))
  expect(new URL(writeScenarioUrl(href, useScenarioStore.getState())).searchParams.get('note')).toBe('keep')
})

it('rejects unsupported view values and orphan variant/evidence state', () => {
  expect(readScenarioUrl('http://localhost/?level=99&mode=invalid&tab=bad&variant_id=v&sim_evidence_id=e')).toMatchObject({ viewLevel: 0, viewMode: 'architecture', activeTab: 'timeline', scenarioId: null, variantId: null, simEvidenceId: null })
})

it('browser back restores state atomically without another history entry', () => {
  const initial = 'http://localhost/?scenario_id=a&variant_id=v'
  let href = initial
  const listeners = new Map<string, () => void>()
  const pushState = vi.fn((_state, _title, next) => { href = String(next) })
  const browser = { location: { get href() { return href } }, history: { pushState },
    addEventListener: (name: string, fn: () => void) => listeners.set(name, fn),
    removeEventListener: (name: string) => listeners.delete(name) }
  const stop = installScenarioUrlSync(browser as unknown as Window)
  try {
    expect(useScenarioStore.getState().scenarioId).toBe('a')
    useScenarioStore.getState().setScenarioId('b')
    expect(new URL(href).searchParams.get('scenario_id')).toBe('b')
    expect(pushState).toHaveBeenCalledOnce()
    useScenarioStore.getState().setSelectedTaskId('transient')
    expect(pushState).toHaveBeenCalledOnce()
    href = initial
    listeners.get('popstate')!()
    expect(useScenarioStore.getState()).toMatchObject({ scenarioId: 'a', variantId: 'v', selectedTaskId: null })
    expect(pushState).toHaveBeenCalledOnce()
  } finally { stop() }
  expect(listeners.has('popstate')).toBe(false)
})
