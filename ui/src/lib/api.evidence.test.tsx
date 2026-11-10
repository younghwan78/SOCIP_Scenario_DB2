// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, invalidateCache, useEvidenceDetail } from './api'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
let host: HTMLDivElement, root: ReturnType<typeof createRoot>
beforeEach(() => {
  invalidateCache('/evidence')
  host = document.createElement('div'); root = createRoot(host)
})
afterEach(() => { act(() => root.unmount()); vi.unstubAllGlobals(); invalidateCache('/evidence') })
const response = (id: string) => new Response(JSON.stringify({ id, kind: 'evidence.simulation', calculation_trace: { full: true } }), { status: 200 })
function Reader({ id }: { id?: string }) {
  const q = useEvidenceDetail(id)
  return <span>{q.loading ? '불러오는 중…' : q.data?.id ?? '선택 없음'}</span>
}

it('evidenceList requests the summary view with scenario, variant and project filters', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }))
  vi.stubGlobal('fetch', fetcher)
  await api.evidenceList('s', 'v', 'p')
  const url = new URL(fetcher.mock.calls[0][0] as string, 'http://local')
  expect(url.pathname).toBe('/api/v1/evidence')
  expect(Object.fromEntries(url.searchParams)).toMatchObject({ view: 'summary', scenario_ref: 's', variant_ref: 'v', project_ref: 'p' })
})

it('selected detail hooks share one HTTP request and reuse cached detail when selection returns', async () => {
  const fetcher = vi.fn().mockImplementation(async (url: string) => response(url.split('/').pop()!))
  vi.stubGlobal('fetch', fetcher)
  await act(async () => { root.render(<><Reader id="one" /><Reader id="one" /></>) })
  expect(fetcher).toHaveBeenCalledTimes(1)
  expect(host.textContent).toBe('oneone')
  expect(fetcher.mock.calls[0][0]).toBe('/api/v1/evidence/one')
  await act(async () => { root.render(<><Reader id="two" /><Reader id="two" /></>) })
  expect(fetcher).toHaveBeenCalledTimes(2)
  expect(host.textContent).toBe('twotwo')
  await act(async () => { root.render(<><Reader id="one" /><Reader id="one" /></>) })
  expect(fetcher).toHaveBeenCalledTimes(2)
  expect(host.textContent).toBe('oneone')
})

it('does not fetch without a selected evidence', async () => {
  const fetcher = vi.fn()
  vi.stubGlobal('fetch', fetcher)
  await act(async () => { root.render(<Reader />) })
  expect(fetcher).not.toHaveBeenCalled()
  expect(host.textContent).toBe('선택 없음')
})
