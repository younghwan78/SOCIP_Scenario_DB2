// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import type { Ctx } from '../src/App'
import { api } from '../src/lib/api'
import { useSimProfiles } from '../src/lib/simProfile'
import { timingApi } from '../src/lib/timingBudget'
import { TimingBudgetPage } from '../src/pages/TimingBudget'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

function Probe({ project, param }: { project: string; param?: string }) {
  const state = useSimProfiles(project, param)
  return <div>{JSON.stringify(state)}</div>
}

it('blocks calculation and shows the profile lookup failure', async () => {
  const profiles = vi.spyOn(api, 'simConfigs').mockRejectedValue(new Error('profile lookup failed'))
  const calculate = vi.spyOn(timingApi, 'variant')
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<TimingBudgetPage ctx={{ project: 'p', scenario: 's', variant: 'v', params: {}, navigate: vi.fn() } as unknown as Ctx} />))
    expect(host.textContent).toContain('profile lookup failed')
    expect(calculate).not.toHaveBeenCalled()
  } finally { act(() => root.unmount()); profiles.mockRestore(); calculate.mockRestore() }
})

it('blocks an unavailable explicit profile and clears the old project selection while loading', async () => {
  const profiles = vi.spyOn(api, 'simConfigs').mockResolvedValue({ items: [{ id: 'v2', version: 2 }] } as Awaited<ReturnType<typeof api.simConfigs>>)
  const host = document.createElement('div'), root = createRoot(host)
  const state = () => JSON.parse(host.textContent!) as { ready: boolean; ref: string | null; error?: string }
  try {
    await act(async () => root.render(<Probe project="one" />))
    expect(state()).toMatchObject({ ready: true, ref: 'v2' })
    await act(async () => root.render(<Probe project="one" param="gone" />))
    expect(state()).toMatchObject({ ready: false, ref: null })
    expect(state().error).toContain('gone')
    profiles.mockImplementation(() => new Promise(() => {}))
    await act(async () => root.render(<Probe project="two" />))
    expect(state()).toMatchObject({ ready: false, ref: null })
  } finally { act(() => root.unmount()); profiles.mockRestore() }
})
