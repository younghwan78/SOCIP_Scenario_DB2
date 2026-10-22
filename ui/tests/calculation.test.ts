import { afterEach, expect, it, vi } from 'vitest'
import { postCalculation } from '../src/lib/calculation'
import { setApiCredential } from '../src/lib/auth'
import { admissionState } from '../src/lib/admission'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); setApiCredential(null) })
const deferred = () => {
  let resolve!: (response: Response) => void
  const promise = new Promise<Response>((done) => { resolve = done })
  return { promise, resolve: (value: unknown) => resolve(new Response(JSON.stringify(value))) }
}

it('shares concurrent identical calculations but fetches a fresh result after completion', async () => {
  const pending = deferred(), fetcher = vi.fn().mockReturnValue(pending.promise)
  vi.stubGlobal('fetch', fetcher)
  const first = postCalculation('/cpu/sweep', { growth: 1 })
  const second = postCalculation('/cpu/sweep', { growth: 1 })
  expect(fetcher).toHaveBeenCalledTimes(1)
  pending.resolve({ result: 10 })
  expect(await first).toEqual({ result: 10 })
  expect(await second).toEqual({ result: 10 })
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ result: 20 })))
  expect(await postCalculation('/cpu/sweep', { growth: 1 })).toEqual({ result: 20 })
  expect(fetcher).toHaveBeenCalledTimes(2)
})

it('never shares different requests, endpoints or identities', async () => {
  const fetcher = vi.fn().mockImplementation(async () => new Response('{}'))
  vi.stubGlobal('fetch', fetcher)
  const calls = [postCalculation('/cpu/sweep', { growth: 1 }), postCalculation('/cpu/sweep', { growth: 2 }), postCalculation('/cpu/rebalance', { growth: 1 })]
  setApiCredential({ keyId: 'next', secret: 'secret' })
  calls.push(postCalculation('/cpu/sweep', { growth: 1 }))
  await Promise.all(calls)
  expect(fetcher).toHaveBeenCalledTimes(4)
  expect((fetcher.mock.calls[3][1].headers as Headers).get('X-ScenarioDB-Key-Id')).toBe('next')
})

it('cancels one subscriber without stopping another and lets a same-turn replacement adopt the request', async () => {
  const pending = deferred(), fetcher = vi.fn().mockReturnValue(pending.promise)
  vi.stubGlobal('fetch', fetcher)
  const old = new AbortController()
  const first = postCalculation('/cpu/rebalance', {}, old.signal)
  const rejected = expect(first).rejects.toMatchObject({ name: 'AbortError' })
  old.abort()
  const current = new AbortController()
  const replacement = postCalculation('/cpu/rebalance', {}, current.signal)
  await rejected
  expect(fetcher).toHaveBeenCalledTimes(1)
  expect((fetcher.mock.calls[0][1].signal as AbortSignal).aborted).toBe(false)
  pending.resolve({ result: 12 })
  expect(await replacement).toEqual({ result: 12 })
})

it('stops queued admission retries after the final subscriber cancels', async () => {
  vi.useFakeTimers()
  const fetcher = vi.fn().mockResolvedValue(new Response('', { status: 429, headers: { 'Retry-After': '1' } }))
  vi.stubGlobal('fetch', fetcher)
  const controller = new AbortController()
  const pending = postCalculation('/cpu/growth-sweep', {}, controller.signal)
  const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  await vi.advanceTimersByTimeAsync(0)
  expect(admissionState().waiting).toBe(1)
  controller.abort()
  await rejected
  await vi.advanceTimersByTimeAsync(10_000)
  expect(admissionState().waiting).toBe(0)
  expect(fetcher).toHaveBeenCalledTimes(1)
  expect((fetcher.mock.calls[0][1].signal as AbortSignal).aborted).toBe(true)
})

it('does not dispatch an already cancelled request', async () => {
  const fetcher = vi.fn(), controller = new AbortController()
  vi.stubGlobal('fetch', fetcher)
  controller.abort()
  await expect(postCalculation('/cpu/sweep', {}, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
  expect(fetcher).not.toHaveBeenCalled()
})

it('keeps simultaneous consumers independent when one cancels or mutates its result', async () => {
  const pending = deferred(), fetcher = vi.fn().mockReturnValue(pending.promise)
  vi.stubGlobal('fetch', fetcher)
  const controller = new AbortController()
  const cancelled = postCalculation('/cpu/sweep', { test: 'isolation' }, controller.signal)
  const first = postCalculation<{ nested: { value: number } }>('/cpu/sweep', { test: 'isolation' })
  const second = postCalculation<{ nested: { value: number } }>('/cpu/sweep', { test: 'isolation' })
  const rejected = expect(cancelled).rejects.toMatchObject({ name: 'AbortError' })
  controller.abort()
  await rejected
  expect((fetcher.mock.calls[0][1].signal as AbortSignal).aborted).toBe(false)
  pending.resolve({ nested: { value: 1 } })
  const one = await first, two = await second
  one.nested.value = 9
  expect(two.nested.value).toBe(1)
  expect(fetcher).toHaveBeenCalledTimes(1)
})
