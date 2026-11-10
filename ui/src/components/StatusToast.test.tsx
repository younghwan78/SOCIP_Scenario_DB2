// @vitest-environment jsdom
import { act, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { StatusToast } from './StatusToast'
import { dismissStatus, notify } from '../lib/status'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
let host: HTMLDivElement
let root: ReturnType<typeof createRoot>
let ids: number[]
beforeEach(() => {
  vi.useFakeTimers(); ids = []
  host = document.createElement('div'); root = createRoot(host)
  act(() => root.render(<StrictMode><StatusToast /></StrictMode>))
})
afterEach(() => { act(() => root.unmount()); ids.forEach(dismissStatus); vi.useRealTimers() })
const post = (kind: 'ok' | 'error' | 'info', text: string) => act(() => { ids.push(notify({ kind, text })) })

it('adds notifications to the existing polite live region', () => {
  const region = host.querySelector('[role="status"][aria-live="polite"]')!
  expect(region.textContent).toBe('')
  post('ok', '저장했습니다.')
  expect(region.textContent).toContain('저장했습니다.')
  expect(host.querySelectorAll('[aria-label="작업 알림"]')).toHaveLength(1)
})

it.each(['ok', 'info'] as const)('dismisses %s after five seconds', (kind) => {
  post(kind, '완료 알림')
  act(() => vi.advanceTimersByTime(4999))
  expect(host.textContent).toContain('완료 알림')
  act(() => vi.advanceTimersByTime(1))
  expect(host.textContent).not.toContain('완료 알림')
})

it('keeps an error alert until explicitly closed', () => {
  post('error', '등록 실패')
  act(() => vi.advanceTimersByTime(60000))
  expect(host.querySelector('[role="alert"][aria-live="assertive"]')?.textContent).toContain('등록 실패')
  act(() => host.querySelector<HTMLButtonElement>('[aria-label="알림 닫기: 등록 실패"]')!.click())
  expect(host.querySelector('[role="alert"]')).toBeNull()
})

it('closes only the selected item and cancels its pending timer', () => {
  post('info', 'first'); post('error', 'second')
  act(() => host.querySelector<HTMLButtonElement>('[aria-label="알림 닫기: first"]')!.click())
  expect(host.textContent).not.toContain('first')
  expect(host.textContent).toContain('second')
  expect(vi.getTimerCount()).toBe(0)
})
