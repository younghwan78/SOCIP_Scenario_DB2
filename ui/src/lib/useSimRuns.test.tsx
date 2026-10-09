// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { useSimRuns } from './useSimRuns'
import * as simRun from './simRun'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
const host = document.createElement('div')
let root = createRoot(host)
let runs: ReturnType<typeof useSimRuns>
function Harness() { runs = useSimRuns(); return null }
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((r) => { resolve = r }); return { promise, resolve } }
const done = (id: string): Extract<simRun.SimState, { status: 'done' }> => ({
  status: 'done', req: { scenario_id: id, variant_id: 'v', execution_context: {} as never, expected_params_hash: '0123456789abcdef' },
  res: { evidence_id: id, params_hash: '0123456789abcdef', kpi: {}, persisted: false },
})
afterEach(() => { act(() => root.unmount()); root = createRoot(host); vi.restoreAllMocks() })

it('ignores a cancelled preview after selecting and running another scenario', async () => {
  await act(async () => root.render(<Harness />))
  const slow = deferred<ReturnType<typeof done>>()
  let old!: Promise<unknown>
  act(() => { old = runs.run('a', () => slow.promise) })
  await act(async () => { runs.cancel('a'); await runs.run('b', async () => done('b')) })
  await act(async () => { slow.resolve(done('a')); await old })
  expect(runs.sims.a).toBeUndefined()
  expect(runs.sims.b).toEqual(done('b'))
})

it('blocks duplicate saves and reruns, then ignores an old save after replacing its preview', async () => {
  await act(async () => root.render(<Harness />))
  await act(async () => { await runs.run('a', async () => done('old')) })
  const slow = deferred<Extract<simRun.SaveState, { status: 'saved' }>>()
  const save = vi.spyOn(simRun, 'saveResult').mockReturnValue(slow.promise)
  let old!: Promise<unknown>
  act(() => { old = runs.save('a') })
  const redundantRun = vi.fn(async () => done('duplicate'))
  await act(async () => { await runs.save('a'); await runs.run('a', redundantRun) })
  expect(save).toHaveBeenCalledTimes(1)
  expect(redundantRun).not.toHaveBeenCalled()
  await act(async () => { runs.cancel('a'); await runs.run('a', async () => done('new')) })
  await act(async () => { slow.resolve({ status: 'saved', evidence_id: 'old', existed: false }); await old })
  expect(runs.sims.a).toEqual(done('new'))
})
