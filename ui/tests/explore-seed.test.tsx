// @vitest-environment jsdom
import { act, StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import type { Ctx } from '../src/App'
import { ExplorePage } from '../src/pages/Explore'
import { archApi, type RunDetail } from '../src/lib/archExplore'

vi.mock('../src/lib/simProfile', async (original) => ({
  ...await original<typeof import('../src/lib/simProfile')>(),
  useSimProfiles: () => ({ profiles: [], ref: null, ready: true, basis: null }),
}))
vi.mock('../src/lib/review', async (original) => ({
  ...await original<typeof import('../src/lib/review')>(), useReferences: () => null,
}))
vi.mock('../src/components/ArchCharts', () => ({
  AxisSpread: () => null, BufferSavings: () => null, CompositionBars: () => null, DomainLevels: () => null,
  IpModes: () => null, RangeBoxes: () => null, SplitBar: () => null, SplitLegend: () => null,
}))
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
const host = document.createElement('div')
const root = createRoot(host)
afterEach(() => { act(() => root.render(null)); vi.restoreAllMocks() })

it('shows a newly created run from the summary endpoint, as before', async () => {
  const run = { id: 'new-run', title: 'created', scenario_type: 'test', project_ref: '', variants: [], errors: [],
    summary: { variants: 0, spec_ok: 0, errors: 0, cases: 0, eligible_cases: 0, verified: 0 }, spec: {}, view: 'summary' } as unknown as RunDetail
  vi.spyOn(archApi, 'runs').mockResolvedValue([run])
  vi.spyOn(archApi, 'board').mockResolvedValue({ rows: [] } as never)
  const create = vi.spyOn(archApi, 'createRun').mockResolvedValue(run)
  const read = vi.spyOn(archApi, 'run').mockResolvedValue({ ...run, scenario_type: 'refreshed' })
  function Page() {
    const [params, setParams] = useState<Record<string, string>>({})
    const ctx = { project: '', scenario: 's', catalog: [], params,
      navigate: (_page: unknown, next: Record<string, string>) => setParams(next) } as unknown as Ctx
    return <ExplorePage ctx={ctx} />
  }
  await act(async () => root.render(<StrictMode><Page /></StrictMode>))
  const start = [...host.querySelectorAll('button')].find((button) => button.textContent === '탐색 실행')!
  expect(start.disabled).toBe(false)
  await act(async () => start.click())
  expect(create).toHaveBeenCalledTimes(1)
  // The POST response is not reused for display: the page reads GET ?view=summary (SQL projection).
  expect(read).toHaveBeenCalledWith('new-run')
  expect(host.querySelector('[aria-label="run 요약"]')).not.toBeNull()
  expect(host.textContent).toContain('refreshed')
})
