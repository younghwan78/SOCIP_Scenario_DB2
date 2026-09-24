// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import { addComparison, useAsync } from '../src/lib/route'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
const host = document.createElement('div')
let root = createRoot(host)
afterEach(() => { act(() => root.unmount()); root = createRoot(host) })

it('never exposes a previous selection while the next request is pending or late', async () => {
  const pending = new Map<string, (value: string) => void>()
  const renders: string[] = []
  function Probe({ id }: { id: string }) {
    const q = useAsync(() => new Promise<string>((resolve) => pending.set(id, resolve)), [id])
    renders.push(`${id}:${q.data ?? 'pending'}`)
    return <span>{q.data ?? 'pending'}</span>
  }
  await act(async () => root.render(<Probe id="a" />))
  await act(async () => pending.get('a')!('A'))
  expect(host.textContent).toBe('A')
  await act(async () => root.render(<Probe id="b" />))
  expect(host.textContent).toBe('pending')
  expect(renders).not.toContain('b:A')
  await act(async () => root.render(<Probe id="c" />))
  await act(async () => pending.get('b')!('B'))
  expect(host.textContent).toBe('pending')
  await act(async () => pending.get('c')!('C'))
  expect(host.textContent).toBe('C')
})

it('keeps comparisons unique and resets them when the scenario changes', () => {
  expect(addComparison('s1', 'a,b', 's1', 'b')).toBe('a,b')
  expect(addComparison('s1', 'a,b', 's2', 'c')).toBe('c')
})
