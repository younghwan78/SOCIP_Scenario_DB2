// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { setApiCredential } from './auth'
import { getJson, postJson } from './api'
import { archApi } from './archExplore'
import { timingApi } from './timingBudget'

afterEach(() => { setApiCredential(null); vi.restoreAllMocks(); vi.unstubAllGlobals() })
it('sends session credentials through read, write, arch and timing helpers without storing them', async () => {
  const write = vi.spyOn(Storage.prototype, 'setItem')
  const fetcher = vi.fn(async () => new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetcher)
  setApiCredential({ keyId: 'analyst-1', secret: 'temporary-test-secret' })
  await getJson('/credential-test', {}, false)
  await postJson('/credential-test', { hello: 'world' })
  await archApi.board('scenario', 'project')
  await timingApi.register('scenario', 'variant', { statistic: 'max', eis: 'auto', runtime_scale: 1 }, 'reason', undefined, undefined, 'project', 'hash', null)
  expect(write).not.toHaveBeenCalled()
  for (const call of fetcher.mock.calls) {
    const [url, init] = call as unknown as [string, RequestInit]
    expect(url).not.toContain('temporary-test-secret')
    const headers = new Headers(init.headers)
    expect(headers.get('X-ScenarioDB-Key-Id')).toBe('analyst-1')
    expect(headers.get('X-ScenarioDB-API-Key')).toBe('temporary-test-secret')
    expect(init.body ?? '').not.toContain('temporary-test-secret')
  }
  setApiCredential(null)
  await getJson('/credential-test', {}, false)
  expect(new Headers((fetcher.mock.calls[fetcher.mock.calls.length - 1] as unknown as [string, RequestInit])[1].headers).has('X-ScenarioDB-API-Key')).toBe(false)
})
it('never returns one account cached GET results after changing credentials', async () => {
  let n = 0
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ n: ++n }), { status: 200 })))
  setApiCredential({ keyId: 'a', secret: 'one' })
  expect(await getJson('/identity-cache')).toEqual({ n: 1 })
  expect(await getJson('/identity-cache')).toEqual({ n: 1 })
  setApiCredential({ keyId: 'b', secret: 'two' })
  expect(await getJson('/identity-cache')).toEqual({ n: 2 })
})

it.each(['arch', 'generic'])('deduplicates %s reads within one actor and separates pending reads across actors', async (helper) => {
  const resolvers: ((response: Response) => void)[] = []
  const fetcher = vi.fn(() => new Promise<Response>((resolve) => resolvers.push(resolve)))
  vi.stubGlobal('fetch', fetcher)
  const read = () => helper === 'arch' ? archApi.board('inflight-scenario') : getJson('/inflight-identity', {}, false)
  setApiCredential({ keyId: 'a', secret: 'one' })
  const first = read(), sameActor = read()
  expect(fetcher).toHaveBeenCalledTimes(1)
  setApiCredential({ keyId: 'b', secret: 'two' })
  const otherActor = read()
  expect(fetcher).toHaveBeenCalledTimes(2)
  resolvers[1](new Response(JSON.stringify({ actor: 'b' }), { status: 200 }))
  expect(await otherActor).toEqual({ actor: 'b' })
  resolvers[0](new Response(JSON.stringify({ actor: 'a' }), { status: 200 }))
  expect(await first).toEqual({ actor: 'a' })
  expect(await sameActor).toEqual({ actor: 'a' })
  const next = read()
  expect(fetcher).toHaveBeenCalledTimes(3)
  resolvers[2](new Response('{}', { status: 200 }))
  await next
})
