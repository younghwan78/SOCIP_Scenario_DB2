import { afterEach, expect, it, vi } from 'vitest'
import { TimelineEngine } from '../src/engine/timeline/TimelineEngine'
import { useScenarioStore } from '../src/store/scenarioStore'

afterEach(() => vi.unstubAllGlobals())

it('drag pans both endpoints equally and detach disconnects the observer', () => {
  const handlers = new Map<string, (event: unknown) => void>()
  const addEventListener = (name: string, handler: (event: unknown) => void) => handlers.set(name, handler)
  const disconnect = vi.fn()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect = disconnect })
  vi.stubGlobal('window', { devicePixelRatio: 1, addEventListener, removeEventListener: vi.fn() })
  vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1))
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  const canvas = { getContext: () => ({ scale: vi.fn() }), getBoundingClientRect: () => ({ left: 0, top: 0, width: 1220, height: 600 }), addEventListener, removeEventListener: vi.fn(), style: {} }
  const engine = new TimelineEngine()
  engine.attach(canvas as unknown as HTMLCanvasElement)
  engine.setData([{ task_id: 'a', start_ms: 0, end_ms: 100, duration_ms: 100 }])
  const state = engine as unknown as { transform: { startMs: number; endMs: number; scale: number } }
  const before = { ...state.transform }
  handlers.get('mousedown')!({ button: 0, clientX: 500, clientY: 300, offsetX: 500, offsetY: 300 })
  handlers.get('mousemove')!({ clientX: 400, clientY: 300 })
  expect(state.transform.endMs - state.transform.startMs).toBeCloseTo(before.endMs - before.startMs)
  expect(state.transform.startMs - before.startMs).toBeCloseTo(100 / before.scale)
  expect(state.transform.endMs - before.endMs).toBeCloseTo(100 / before.scale)
  engine.detach()
  expect(disconnect).toHaveBeenCalledOnce()
})

it('changing scenario clears task and evidence context', () => {
  useScenarioStore.setState({ scenarioId: 'a', variantId: 'v', selectedTaskId: 'task-a', simEvidenceId: 'ev-a', simOverlayMode: 'specific', expandTarget: 'old-node' })
  useScenarioStore.getState().setScenarioId('b')
  expect(useScenarioStore.getState()).toMatchObject({ scenarioId: 'b', variantId: null, selectedTaskId: null, simEvidenceId: null, simOverlayMode: 'none', expandTarget: null })
})
