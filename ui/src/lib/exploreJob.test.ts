// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { archApi } from './archExplore'
import { _resetExploreJob, restoreExploreJob, trackExploreJob, useExploreJob, type ExploreJob } from './exploreJob'
import { dismissStatus, notify } from './status'

vi.mock('./status', () => ({ notify: vi.fn(), dismissStatus: vi.fn() }))

const job = (over: Partial<ExploreJob> = {}): ExploreJob => ({ id: 'explore-job-1', status: 'running', completed_variants: 1, total_variants: 4,
  current_variant: 'v1', failed_variants: 0, run_id: null, summary: null, cancel_requested: false, error: null, resumable: false, ...over })

beforeEach(() => { vi.useFakeTimers(); localStorage.clear() })
afterEach(() => { _resetExploreJob(); vi.useRealTimers(); vi.restoreAllMocks(); vi.mocked(notify).mockReset(); void dismissStatus })

it('stores an active job and forgets it once it finishes', async () => {
  vi.spyOn(archApi, 'job').mockResolvedValue(job({ status: 'completed', completed_variants: 4, run_id: 'EXP-1', summary: { variants: 4, errors: 0 } }))
  trackExploreJob(job(), 'Recording', 'proj')
  expect(JSON.parse(localStorage.getItem('sdb.explore.job')!)).toEqual({ id: 'explore-job-1', title: 'Recording', project: 'proj' })
  await vi.advanceTimersByTimeAsync(1000)
  expect(localStorage.getItem('sdb.explore.job')).toBeNull()
  expect(notify).toHaveBeenCalledWith({ kind: 'ok', text: '탐색 완료: Recording · variant 4개' })
})

it('picks up a job left running before a reload and reports its end once', async () => {
  localStorage.setItem('sdb.explore.job', JSON.stringify({ id: 'explore-job-1', title: 'Recording', project: null }))
  const poll = vi.spyOn(archApi, 'job').mockResolvedValueOnce(job())
    .mockResolvedValue(job({ status: 'failed', error: 'every variant failed (4)', resumable: true }))
  restoreExploreJob()
  await vi.advanceTimersByTimeAsync(0)
  expect(poll).toHaveBeenCalledWith('explore-job-1')
  await vi.advanceTimersByTimeAsync(1000)
  await vi.advanceTimersByTimeAsync(5000)
  expect(vi.mocked(notify).mock.calls).toEqual([[{ kind: 'error', text: '탐색 실패: Recording · every variant failed (4)' }]])
  expect(localStorage.getItem('sdb.explore.job')).toBeNull()
})

it('stops tracking a job the server no longer knows', async () => {
  vi.spyOn(archApi, 'job').mockRejectedValue(new Error('404 Not Found'))
  trackExploreJob(job(), 'Recording', null)
  await vi.advanceTimersByTimeAsync(1000)
  expect(localStorage.getItem('sdb.explore.job')).toBeNull()
  expect(vi.mocked(notify).mock.calls[0][0].text).toContain('404 Not Found')
  void useExploreJob
})
