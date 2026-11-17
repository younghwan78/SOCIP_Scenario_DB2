// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest'
import { clearLayoutCache, elkUsesWorker, layoutCacheSize, layoutGraph, type Graph } from './graph'

afterEach(() => clearLayoutCache())

const graph = (label = 'ISP'): Graph => ({
  nodes: [
    { id: 'a', label, kind: 'ip', width: 120, height: 40 },
    { id: 'b', label: 'MCSC', kind: 'ip', width: 120, height: 40 },
  ],
  groups: [],
  edges: [{ id: 'e1', source: 'a', target: 'b', kind: 'otf' }],
} as unknown as Graph)

it('lays out without a Worker on the main-thread build (tests / no Worker)', async () => {
  expect(elkUsesWorker()).toBe(typeof Worker !== 'undefined')
  const layout = await layoutGraph(graph())
  const [a, b] = ['a', 'b'].map((id) => layout.nodes.find((n) => n.id === id)!)
  expect(b.y).toBeGreaterThan(a.y)                     // DOWN: the consumer below the producer
  expect(layout.edges[0].points.length).toBeGreaterThanOrEqual(2)
})

it('reuses the layout of the same structure and keeps the current labels', async () => {
  const first = await layoutGraph(graph('ISP'))
  expect(layoutCacheSize()).toBe(1)
  const again = await layoutGraph(graph('ISP v2'))      // same ids / sizes / edges: a cache hit
  expect(layoutCacheSize()).toBe(1)
  expect(again.nodes.map((n) => [n.id, n.x, n.y])).toEqual(first.nodes.map((n) => [n.id, n.x, n.y]))
  expect(again.nodes.find((n) => n.id === 'a')?.label).toBe('ISP v2')
  const wider = graph(); (wider.nodes[0] as { width: number }).width = 300
  await layoutGraph(wider)                              // another size: another layout
  expect(layoutCacheSize()).toBe(2)
})
