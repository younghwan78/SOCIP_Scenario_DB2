// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ErrorBoundary } from './ErrorBoundary'
import { notify } from '../lib/status'

vi.mock('../lib/status', () => ({ notify: vi.fn() }))
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
let host: HTMLDivElement
let root: ReturnType<typeof createRoot>
const expectedRenderError = (event: ErrorEvent) => { if (event.error?.message === 'page render failed') event.preventDefault() }
beforeEach(() => {
  host = document.createElement('div'); root = createRoot(host)
  vi.spyOn(console, 'error').mockImplementation(() => {})
  window.addEventListener('error', expectedRenderError)
})
afterEach(() => { act(() => root.unmount()); window.removeEventListener('error', expectedRenderError); vi.restoreAllMocks(); Reflect.deleteProperty(navigator, 'clipboard') })
function Broken(): never { throw new Error('page render failed') }

it('shows the page name and error, then retries rendering the child', () => {
  let broken = true
  function Page() { return broken ? <Broken /> : <p>recovered</p> }
  act(() => root.render(<ErrorBoundary pageKey="explore" pageName="조합 탐색"><Page /></ErrorBoundary>))
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('조합 탐색 화면을 표시하지 못했습니다.')
  expect(host.textContent).toContain('page render failed')
  broken = false
  act(() => host.querySelector<HTMLButtonElement>('button')!.click())
  expect(host.textContent).toBe('recovered')
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
