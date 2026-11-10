// @vitest-environment jsdom
import { act, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ErrorBoundary } from './ErrorBoundary'
import { notify } from '../lib/status'

vi.mock('../lib/status', () => ({ notify: vi.fn() }))
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
let host: HTMLDivElement
let root: ReturnType<typeof createRoot>
const chunkErrors = [
  Object.assign(new Error('A script could not be loaded'), { name: 'ChunkLoadError' }),
  new TypeError('Failed to fetch dynamically imported module: /assets/page.js'),
  new TypeError('Importing a module script failed.'),
  new TypeError('error loading dynamically imported module: /assets/page.js'),
  new Error('Loading chunk 7 failed.'),
]
const expectedRenderError = (event: ErrorEvent) => {
  if (event.error?.message === 'page render failed' || chunkErrors.some((error) => error.message === event.error?.message)) event.preventDefault()
}
beforeEach(() => {
  host = document.createElement('div'); root = createRoot(host)
  vi.spyOn(console, 'error').mockImplementation(() => {})
  window.addEventListener('error', expectedRenderError)
})
afterEach(() => { vi.unstubAllGlobals(); act(() => root.unmount()); window.removeEventListener('error', expectedRenderError); vi.restoreAllMocks(); Reflect.deleteProperty(navigator, 'clipboard') })
function Broken(): never { throw new Error('page render failed') }
function mockReload() {
  const reload = vi.fn()
  const location = { ...window.location, reload }
  vi.stubGlobal('window', new Proxy(window, { get: (target, key) => key === 'location' ? location : Reflect.get(target, key) }))
  return reload
}

it('shows the page name and error, then retries rendering the child', () => {
  const reload = mockReload()
  let broken = true
  function Page() { return broken ? <Broken /> : <p>recovered</p> }
  act(() => root.render(<ErrorBoundary pageKey="explore" pageName="조합 탐색"><Page /></ErrorBoundary>))
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('조합 탐색 화면을 표시하지 못했습니다.')
  expect(host.textContent).toContain('page render failed')
  expect(host.querySelector('button')?.textContent).toBe('다시 시도')
  broken = false
  act(() => host.querySelector<HTMLButtonElement>('button')!.click())
  expect(host.textContent).toBe('recovered')
  expect(reload).not.toHaveBeenCalled()
})

it.each(chunkErrors)('reloads for a rejected lazy import instead of retrying the cached error: %s', async (error) => {
  const reload = mockReload()
  const load = vi.fn(async () => { throw error })
  const Page = lazy(load)
  await act(async () => root.render(<Suspense fallback={<p>loading</p>}><ErrorBoundary pageKey="explore" pageName="조합 탐색"><Page /></ErrorBoundary></Suspense>))
  expect(host.textContent).toContain(error.message)
  expect(host.textContent).toContain('화면 코드를 불러오지 못했습니다. 새로고침하여 다시 불러오세요.')
  expect(host.querySelector('button')?.textContent).toBe('새로고침')
  act(() => host.querySelector<HTMLButtonElement>('button')!.click())
  expect(reload).toHaveBeenCalledTimes(1)
  expect(load).toHaveBeenCalledTimes(1)
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(error.message)
})

it('resets a failed boundary when the route key changes', () => {
  act(() => root.render(<ErrorBoundary pageKey="explore" pageName="조합 탐색"><Broken /></ErrorBoundary>))
  act(() => root.render(<ErrorBoundary pageKey="settings" pageName="설정"><p>settings works</p></ErrorBoundary>))
  expect(host.querySelector('[role="alert"]')).toBeNull()
  expect(host.textContent).toBe('settings works')
})

it('copies the message, stack and current hash route', async () => {
  const copy = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: copy } })
  window.history.replaceState(null, '', '#/explore?run=test')
  act(() => root.render(<ErrorBoundary pageKey="explore" pageName="조합 탐색"><Broken /></ErrorBoundary>))
  await act(async () => [...host.querySelectorAll('button')].find((button) => button.textContent === '오류 복사')!.click())
  expect(copy).toHaveBeenCalledWith(expect.stringContaining('Error: page render failed\n'))
  expect(copy).toHaveBeenCalledWith(expect.stringContaining('Route: #/explore?run=test'))
  expect(notify).toHaveBeenCalledWith({ kind: 'ok', text: '오류 내용을 복사했습니다.' })
})

it('announces a clipboard failure without losing the fallback', async () => {
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } })
  act(() => root.render(<ErrorBoundary pageKey="explore" pageName="조합 탐색"><Broken /></ErrorBoundary>))
  await act(async () => [...host.querySelectorAll('button')].find((button) => button.textContent === '오류 복사')!.click())
  expect(notify).toHaveBeenCalledWith({ kind: 'error', text: expect.stringContaining('복사하지 못했습니다') })
  expect(host.querySelector('[role="alert"]')).not.toBeNull()
})
