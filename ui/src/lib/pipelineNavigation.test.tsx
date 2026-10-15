// @vitest-environment jsdom
import { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { usePipelineNavigation, type Mode } from './pipelineNavigation'
import { useRoute } from './route'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
async function traverse(direction: 'back' | 'forward') {
  await act(async () => {
    const changed = new Promise<void>((resolve) => window.addEventListener('hashchange', () => resolve(), { once: true }))
    window.history[direction]()
    await changed
  })
}

it('restores the default lens and Timing layout across repeated Back/Forward without duplicate IP entries', async () => {
  window.history.replaceState(null, '', '#/pipeline?scenario=s&variant=v')
  const root = createRoot(document.createElement('div'))
  let current!: ReturnType<typeof usePipelineNavigation>, layout!: Mode
  function Harness() {
    const [route, navigate] = useRoute()
    const [mode, setMode] = useState<Mode>('timing')
    layout = mode
    current = usePipelineNavigation({ scenario: 's', variant: 'v', params: route.params,
      navigate: (page, params, replace) => navigate({ page, params }, replace) }, mode, setMode)
    return null
  }
  try {
    await act(async () => root.render(<Harness />))
    const length = window.history.length
    act(() => current.openIpInternal())
    expect(current.lens).toBe('ip'); expect(layout).toBe('split')
    expect(window.history.length).toBe(length + 1)
    act(() => current.openIpInternal())
    expect(window.history.length).toBe(length + 1)
    for (let i = 0; i < 2; i++) {
      await traverse('back')
      expect(current.lens).toBe('sequence'); expect(layout).toBe('timing')
      await traverse('forward')
      expect(current.lens).toBe('ip'); expect(layout).toBe('split')
      expect(current.origin?.lens).toBe('sequence')
    }
  } finally { act(() => root.unmount()) }
})

it('forgets the return target when the scenario changes or a lens tab is chosen', async () => {
  const root = createRoot(document.createElement('div'))
  let current!: ReturnType<typeof usePipelineNavigation>
  const calls: unknown[][] = []
  function Harness({ scenario, lens }: { scenario: string; lens: string }) {
    const [mode, setMode] = useState<Mode>('graph')
    current = usePipelineNavigation({ scenario, variant: 'v', params: { lens },
      navigate: (...args) => calls.push(args) }, mode, setMode)
    return null
  }
  try {
    await act(async () => root.render(<Harness scenario="s" lens="dma" />))
    act(() => current.openIpInternal())
    await act(async () => root.render(<Harness scenario="s" lens="ip" />))
    expect(current.origin?.lens).toBe('dma')
    act(() => current.setLens('sequence'))
    expect(current.origin).toBeNull()
    expect(calls[calls.length - 1]).toEqual([undefined, { lens: 'sequence' }, true])
    await act(async () => root.render(<Harness scenario="s" lens="dma" />))
    act(() => current.openIpInternal())
    await act(async () => root.render(<Harness scenario="other" lens="ip" />))
    expect(current.origin).toBeNull()
  } finally { act(() => root.unmount()) }
})
