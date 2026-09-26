// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import App from '../src/App'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
vi.mock('../src/pages/Pipeline', () => ({ PipelinePage: ({ ctx }: { ctx: { scenario: string; variant: string } }) => <div data-testid="selection">{ctx.scenario}/{ctx.variant}</div> }))
vi.mock('../src/lib/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../src/lib/api')>()
  return { ...original, api: { ...original.api, catalog: async () => ({ items: [
    { scenario_id: 'uc-cam-recording-e2600', project_id: 'p1', scenario_name: 'Recording', variant_count: 2, default_variant_id: 'source-only', category: ['camera'] },
    { scenario_id: 'uc-cam-recording-e2700', project_id: 'p2', scenario_name: 'Recording', variant_count: 1, default_variant_id: 'target-only', category: ['camera'] },
  ], total: 2 }) } }
})

it('switches to a variant actually present in the target project', async () => {
  window.history.replaceState(null, '', '#/pipeline?scenario=uc-cam-recording-e2600&variant=source-only')
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => { root.render(<App />) })
    const selector = host.querySelector<HTMLSelectElement>('select[aria-label="과제 선택"]')!
    expect(selector).not.toBeNull()
    await act(async () => { selector.value = 'p2'; selector.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(host.querySelector('[data-testid="selection"]')?.textContent).toBe('uc-cam-recording-e2700/target-only')
  } finally { act(() => root.unmount()); localStorage.clear() }
})
