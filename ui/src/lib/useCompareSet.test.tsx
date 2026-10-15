// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { useCompareSet } from './useCompareSet'
import { useRoute } from './route'
import { formatItems, loadCompareSet, saveCompareSet } from './projects'
import type { Ctx } from '../App'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
it('restores the kept list, honors legacy URL picks and forgets the list on clear', async () => {
  window.localStorage.clear()
  saveCompareSet('s~a,s~b')
  window.history.replaceState(null, '', '#/compare?scenario=s&variant=current')
  const root = createRoot(document.createElement('div'))
  let current!: ReturnType<typeof useCompareSet>, navigate!: Ctx['navigate']
  function Harness() {
    const [route, nav] = useRoute()
    navigate = (page, params, replace) => nav({ page, params }, replace)
    current = useCompareSet({ params: route.params, scenario: 's', variant: 'current', navigate })
    return null
  }
  try {
    const length = window.history.length
    await act(async () => root.render(<Harness />))
    expect(formatItems(current.items)).toBe('s~a,s~b')
    expect(window.history.length).toBe(length)
    act(() => navigate(undefined, { items: undefined, variants: 'x,y' }))
    expect(formatItems(current.items)).toBe('s~x,s~y')
    expect(loadCompareSet()).toBe('s~x,s~y')
    act(() => navigate(undefined, { items: 's~latest,s~other', variants: undefined }))
    act(() => navigate(undefined, { items: undefined }))
    expect(formatItems(current.items)).toBe('s~latest,s~other')
    act(() => current.clear())
    expect(formatItems(current.items)).toBe('s~current')
    expect(loadCompareSet()).toBe('')
  } finally { act(() => root.unmount()); window.localStorage.clear() }
})
