import { afterEach, expect, it, vi } from 'vitest'
import { calibrationApi } from '../src/lib/calibration'

afterEach(() => vi.unstubAllGlobals())

it('loads complete count coverage in bounded batches with the selected project', async () => {
  const fetcher = vi.fn().mockImplementation(async (url: string) => {
    const query = new URL(url, 'http://test').searchParams
    return new Response(JSON.stringify(Object.fromEntries(query.getAll('scenario_ids').map((id) => [id, { v: { measurement: 2 } }]))))
  })
  vi.stubGlobal('fetch', fetcher)
  const ids = Array.from({ length: 52 }, (_, i) => `s-${i}`)
  const rows = await calibrationApi.coverageBatch([...ids, ids[0]], 'board b')
  expect(rows).toEqual(ids.map((id) => [id, { v: { measurement: 2 } }]))
  expect(fetcher).toHaveBeenCalledTimes(3)
  for (const [url] of fetcher.mock.calls) {
    const q = new URL(url, 'http://test').searchParams
    expect(q.getAll('scenario_ids').length).toBeLessThanOrEqual(25)
    expect(q.get('project_ref')).toBe('board b')
  }
})

it('preserves individual scenario failures when the batch endpoint is unavailable', async () => {
  const fetcher = vi.fn().mockImplementation(async (url: string) => {
    if (url.includes('coverage-counts')) return new Response('old server', { status: 404 })
    if (url.includes('scenario_id=broken')) return new Response('unavailable', { status: 500 })
    return new Response(JSON.stringify({ v: { measurement: 1 } }))
  })
  vi.stubGlobal('fetch', fetcher)
  expect(await calibrationApi.coverageBatch(['good', 'broken'])).toEqual([['good', { v: { measurement: 1 } }], null])
  expect(fetcher).toHaveBeenCalledTimes(3)
  expect(await calibrationApi.coverageBatch([])).toEqual([])
  expect(fetcher).toHaveBeenCalledTimes(3)
})
