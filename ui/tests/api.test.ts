import { afterEach, expect, it, vi } from 'vitest'
import { api, getJson } from '../src/lib/api'

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
