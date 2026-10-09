import { afterEach, expect, it, vi } from 'vitest'
import { cpuApi, type CpuSweepRequest, type CpuWhatIfRequest } from '../src/lib/cpu'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

it.each(['sweep', 'whatif'] as const)('retries CPU %s admission with the same request', async (endpoint) => {
  vi.useFakeTimers()
  const fetcher = vi.fn()
    .mockResolvedValueOnce({ status: 429, headers: { get: () => '1' } })
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ result: { tasks: ['eis'] } }) })
  vi.stubGlobal('fetch', fetcher)
  const request = { power_params_ref: 'pmp', cpu_profile_ref: 'measured', fps: 30 }
  const pending = endpoint === 'sweep'
    ? cpuApi.sweep(request as CpuSweepRequest)
    : cpuApi.whatif(request as CpuWhatIfRequest)
  await vi.runAllTimersAsync()
  await expect(pending).resolves.toEqual({ tasks: ['eis'] })
  expect(fetcher).toHaveBeenCalledTimes(2)
  expect(fetcher.mock.calls[0][0]).toContain(`/cpu/${endpoint}`)
  expect(fetcher.mock.calls[1]).toEqual(fetcher.mock.calls[0])
})

it('stops retrying CPU admission and reports the final error', async () => {
  vi.useFakeTimers()
  const fetcher = vi.fn().mockResolvedValue({
    ok: false, status: 429, statusText: 'Too Many Requests', headers: { get: () => '1' },
    json: async () => ({ detail: 'simulation concurrency limit reached' }),
  })
  vi.stubGlobal('fetch', fetcher)
  const pending = expect(cpuApi.sweep({} as CpuSweepRequest)).rejects.toThrow(/simulation concurrency limit reached/)
  await vi.runAllTimersAsync()
  await pending
  // waits for other users' runs up to the admission budget (2 min) before reporting the 429
  expect(fetcher.mock.calls.length).toBeGreaterThan(20)
})

it('does not retry CPU validation errors', async () => {
  const fetcher = vi.fn().mockResolvedValue({
    ok: false, status: 422, statusText: 'Unprocessable Entity', json: async () => ({ detail: 'unknown profile' }),
  })
  vi.stubGlobal('fetch', fetcher)
  await expect(cpuApi.whatif({} as CpuWhatIfRequest)).rejects.toThrow(/unknown profile/)
  expect(fetcher).toHaveBeenCalledTimes(1)
})
