// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import App from './App'
import { api } from './lib/api'

vi.mock('./pages/Library', () => ({ LibraryPage: () => { throw new Error('library render failed') } }))
vi.mock('./pages/Settings', () => ({ SettingsPage: () => <p>설정 화면 정상</p> }))
vi.mock('./components/Provenance', () => ({ ModelStatusBar: () => null }))
vi.mock('./components/ExperimentContext', () => ({ ExperimentContextBar: () => null }))
vi.mock('./components/Picker', () => ({ Picker: () => null }))
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

it('keeps navigation usable after a lazy page throws and opens another page', async () => {
  vi.spyOn(api, 'catalog').mockResolvedValue({ items: [], total: 0 })
  vi.spyOn(console, 'error').mockImplementation(() => {})
  window.history.replaceState(null, '', '#/library')
  const host = document.createElement('div'), root = createRoot(host)
  const expectedRenderError = (event: ErrorEvent) => { if (event.error?.message === 'library render failed') event.preventDefault() }
  window.addEventListener('error', expectedRenderError)
  try {
    await act(async () => root.render(<App />))
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Library 화면을 표시하지 못했습니다.')
    const nav = host.querySelector('nav[aria-label="주 메뉴"]')!
    const link = nav.querySelector<HTMLAnchorElement>('a[href^="#/settings"]')!
    expect(link).not.toBeNull()
    await act(async () => {
      window.history.replaceState(null, '', link.getAttribute('href'))
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(host.textContent).toContain('설정 화면 정상')
    expect(host.querySelector('[role="alert"]')).toBeNull()
    expect(host.querySelectorAll('[aria-label="작업 알림"]')).toHaveLength(1)
  } finally { act(() => root.unmount()); window.removeEventListener('error', expectedRenderError); localStorage.clear(); vi.restoreAllMocks() }
})
