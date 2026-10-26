// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { addComparison, useAsync } from '../src/lib/route'
import { getJson } from '../src/lib/api'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
const host = document.createElement('div')
let root = createRoot(host)
afterEach(() => { act(() => root.unmount()); root = createRoot(host); vi.unstubAllGlobals() })

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

it('aborts obsolete scoped reads on selection changes and on unmount', async () => {
  const signals: AbortSignal[] = []
  vi.stubGlobal('fetch', vi.fn((_url, init) => {
    signals.push(init.signal)
    return new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))
  }))
  function Probe({ id }: { id: string }) { useAsync(() => getJson(`/scope-cancellation/${id}`), [id]); return null }
  await act(async () => root.render(<Probe id="a" />))
  await act(async () => root.render(<Probe id="b" />))
  expect(signals).toHaveLength(2)
  expect(signals[0].aborted).toBe(true)
  expect(signals[1].aborted).toBe(false)
  await act(async () => root.render(null))
  expect(signals[1].aborted).toBe(true)
})
