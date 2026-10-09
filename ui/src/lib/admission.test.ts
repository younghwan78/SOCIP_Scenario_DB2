import { afterEach, expect, it, vi } from 'vitest'
import { admissionState, backoffMs, fetchAdmitted } from './admission'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

it('backs off from Retry-After up to 5 s', () => {
  expect(backoffMs(0, 1, 0)).toBe(1000)
  expect(backoffMs(2, 1, 0)).toBe(1500)
  expect(backoffMs(40, 2, 0)).toBe(5000)
  expect(backoffMs(0, null, 0)).toBe(1000)
  expect(backoffMs(0, 10, 0)).toBe(10000)
})

it('waits on 429, reports the queue, and returns the admitted response', async () => {
  vi.useFakeTimers()
  const busy = new Response('', { status: 429, headers: { 'Retry-After': '1' } })
  const ok = new Response('{}', { status: 200 })
  const fetchMock = vi.fn().mockResolvedValueOnce(busy).mockResolvedValueOnce(busy.clone()).mockResolvedValueOnce(ok)
  vi.stubGlobal('fetch', fetchMock)
  const p = fetchAdmitted('/x', {})
  await vi.advanceTimersByTimeAsync(0)
  expect(admissionState().waiting).toBe(1)
  await vi.advanceTimersByTimeAsync(5000)
  const res = await p
  expect(res.status).toBe(200)
  expect(fetchMock).toHaveBeenCalledTimes(3)
  expect(admissionState().waiting).toBe(0)
})

it('gives up after the budget and returns the 429', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => new Response('', { status: 429 })))
  const p = fetchAdmitted('/x', {}, 3000)
  await vi.advanceTimersByTimeAsync(10_000)
  expect((await p).status).toBe(429)
  expect(admissionState().waiting).toBe(0)
})

it('cancels a queued request promptly without another retry', async () => {
  vi.useFakeTimers()
  const fetchMock = vi.fn().mockResolvedValue(new Response('', { status: 429 }))
  vi.stubGlobal('fetch', fetchMock)
  const ctrl = new AbortController()
  const p = fetchAdmitted('/x', { signal: ctrl.signal })
  const rejected = expect(p).rejects.toMatchObject({ name: 'AbortError' })
  await vi.advanceTimersByTimeAsync(0)
  expect(admissionState().waiting).toBe(1)
  ctrl.abort()
  await rejected
  expect(admissionState().waiting).toBe(0)
  expect(fetchMock).toHaveBeenCalledTimes(1)
})
