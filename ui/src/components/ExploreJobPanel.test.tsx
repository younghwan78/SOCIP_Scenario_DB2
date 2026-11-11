// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { ExploreJobPanel } from './ExploreJobPanel'
import { _resetExploreJob, trackExploreJob, type ExploreJob } from '../lib/exploreJob'

vi.mock('../lib/status', () => ({ notify: vi.fn(), dismissStatus: vi.fn() }))

const done: ExploreJob = { id: 'explore-job-1', status: 'completed', completed_variants: 3, total_variants: 3, current_variant: null,
  failed_variants: 0, run_id: 'EXP-1', summary: { variants: 3, errors: 0, spec_ok: 3 }, cancel_requested: false, error: null, resumable: false }

afterEach(() => _resetExploreJob())

const mount = (project: string | null, onOpen: (id: string) => void) => {
  const host = document.createElement('div')
  const root = createRoot(host)
  act(() => root.render(<ExploreJobPanel project={project} onOpen={onOpen} />))
  return { host, unmount: () => act(() => root.unmount()) }
}

it('opens a completed run once, not again after a remount', () => {
  trackExploreJob(done, 'Recording', 'proj-a')
  const onOpen = vi.fn()
  mount('proj-a', onOpen).unmount()
  mount('proj-a', onOpen).unmount()
  expect(onOpen.mock.calls).toEqual([['EXP-1']])
})

it("never opens another project's run on its own", () => {
  trackExploreJob(done, 'Recording', 'proj-a')
  const onOpen = vi.fn()
  const { host, unmount } = mount('proj-b', onOpen)
  expect(onOpen).not.toHaveBeenCalled()
  const open = [...host.querySelectorAll('button')].find((b) => b.textContent?.startsWith('run 열기'))!
  expect(open.textContent).toBe('run 열기 (proj-a · 비교 보기)')
  act(() => open.click())
  expect(onOpen.mock.calls).toEqual([['EXP-1']])
  unmount()
})
