// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { EngineChanges } from './EngineChanges'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

it('lists what changed between an old engine and today, and nothing when there is no change', () => {
  const host = document.createElement('div')
  const root = createRoot(host)
  act(() => root.render(<EngineChanges changes={[{ rev: 15, change: 'SW margin follows the throughput model', moves: 'SW margin' }]} />))
  expect(host.querySelector('summary')?.textContent).toBe('그 사이 engine 변경 1건')
  expect(host.querySelector('li')?.textContent).toBe('rev 15 SW margin follows the throughput model — 움직이는 값: SW margin')
  act(() => root.render(<EngineChanges changes={[]} />))
  expect(host.innerHTML).toBe('')
  act(() => root.unmount())
})
