import { afterEach, expect, it, vi } from 'vitest'
import { api, getJson, invalidateCache } from '../src/lib/api'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

it('refreshes cached data after an import instead of caching it for the entire session', async () => {
  vi.useFakeTimers()
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ revision: 1 }) })
  vi.stubGlobal('fetch', fetcher)
  await getJson('/refresh-test')
  await getJson('/refresh-test')
  expect(fetcher).toHaveBeenCalledTimes(1)
  vi.advanceTimersByTime(60001)
  await getJson('/refresh-test')
  expect(fetcher).toHaveBeenCalledTimes(2)
})

it('loads all variant pages rather than silently truncating the picker', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ items: [{ id: 'a' }], total: 2 }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [{ id: 'b' }], total: 2 }) })
  vi.stubGlobal('fetch', fetcher)
  expect((await api.variants('paged-test')).items.map((r) => r.id)).toEqual(['a', 'b'])
  expect(fetcher.mock.calls[1][0]).toContain('offset=1')
})

it('uses the base view endpoint for a scenario without variants', async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
  vi.stubGlobal('fetch', fetcher)
  await api.view('base-test', '')
  expect(fetcher.mock.calls[0][0]).toBe('/api/v1/scenarios/base-test/view?level=1')
})

it('scopes evidence to the selected board project', async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [], total: 0 }) })
  vi.stubGlobal('fetch', fetcher)
  await api.evidenceList('s-test', 'v-test', 'board-test')
  expect(fetcher.mock.calls[0][0]).toContain('project_ref=board-test')
})

it('cancels one reader without poisoning an identical request used by another reader', async () => {
  let finish!: (value: unknown) => void
  let fetchSignal: AbortSignal | undefined
  vi.stubGlobal('fetch', vi.fn((_url, init) => { fetchSignal = init.signal; return new Promise((resolve) => { finish = resolve }) }))
  const left = new AbortController(), right = new AbortController()
  const first = getJson('/shared-abort-test', {}, false, left.signal)
  const rejected = expect(first).rejects.toMatchObject({ name: 'AbortError' })
  const second = getJson('/shared-abort-test', {}, false, right.signal)
  left.abort()
  await rejected
  expect(fetchSignal?.aborted).toBe(false)
  finish({ ok: true, json: async () => ({ value: 7 }) })
  await expect(second).resolves.toEqual({ value: 7 })
})

it('aborts the transport when its final reader leaves and permits a fresh retry', async () => {
  const signals: AbortSignal[] = []
  const fetcher = vi.fn((_url, init) => {
    signals.push(init.signal)
    if (signals.length > 1) return Promise.resolve({ ok: true, json: async () => ({ fresh: true }) })
    return new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))
  })
  vi.stubGlobal('fetch', fetcher)
  const controller = new AbortController()
  const pending = getJson('/last-abort-test', {}, true, controller.signal)
  const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  controller.abort()
  await rejected
  expect(signals[0].aborted).toBe(true)
  await expect(getJson('/last-abort-test')).resolves.toEqual({ fresh: true })
  expect(fetcher).toHaveBeenCalledTimes(2)
})

it.each([true, false])('detaches invalidated pending reads without cancelling existing subscribers (cached=%s)', async (cached) => {
  const pending: { signal: AbortSignal; finish: (value: unknown) => void }[] = []
  const fetcher = vi.fn((_url, init) => new Promise((finish) => pending.push({ signal: init.signal, finish })))
  vi.stubGlobal('fetch', fetcher)
  const path = `/invalidation-race-${cached}`
  const oldRead = getJson(path, {}, cached)
  invalidateCache(path)
  const newRead = getJson(path)
  expect(fetcher).toHaveBeenCalledTimes(2)
  expect(pending[0].signal.aborted).toBe(false)
  pending[1].finish({ ok: true, json: async () => ({ revision: 'after-write' }) })
  await expect(newRead).resolves.toEqual({ revision: 'after-write' })
  pending[0].finish({ ok: true, json: async () => ({ revision: 'before-write' }) })
  await expect(oldRead).resolves.toEqual({ revision: 'before-write' })
  await expect(getJson(path)).resolves.toEqual({ revision: 'after-write' })
  expect(fetcher).toHaveBeenCalledTimes(2)
})
