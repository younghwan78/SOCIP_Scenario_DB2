// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Ctx } from '../src/App'
import { cpuApi, type CpuSweep, type CpuSweepRequest } from '../src/lib/cpu'
import { CpuWhatIfPage } from '../src/pages/CpuWhatIf'
import { ChartTipProvider } from '../src/components/ChartTip'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
if (typeof ResizeObserver === 'undefined') Object.assign(globalThis, { ResizeObserver: class { observe() {} unobserve() {} disconnect() {} } })

it('keeps a completed sweep during manual retry but clears it when the reference changes', async () => {
  localStorage.setItem('sdb.cpu.mode', JSON.stringify('sweep'))
  const result = (JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/cpu-dsu-sweeps.json'), 'utf8')) as { measured: CpuSweep }).measured
  result.warnings = ['retained sweep result']
  const inputs = vi.spyOn(cpuApi, 'inputs').mockResolvedValue({
    profiles: [{ id: 'profile', scenario_ref: null, variant_ref: null, project_ref: null }],
    topologies: [{ id: 'target', version: 1, soc_ref: 'soc-exynos2600', clusters: result.range.clusters.map((c) => c.name) }],
  })
  const pending: { resolve: (result: CpuSweep) => void; reject: (reason: Error) => void }[] = []
  const sweep = vi.spyOn(cpuApi, 'sweep').mockImplementation(() => new Promise((resolve, reject) => {
    pending.push({ resolve, reject })
  }))
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<ChartTipProvider><CpuWhatIfPage ctx={{} as Ctx} /></ChartTipProvider>))
    await act(async () => pending[0].resolve(result))
    expect(host.textContent).toContain('retained sweep result')
    const retry = [...host.querySelectorAll<HTMLButtonElement>('button')].find((b) => b.textContent === '다시 계산')!
    await act(async () => retry.click())
    expect(host.textContent).toContain('retained sweep result')
    await act(async () => pending[1].reject(new Error('manual retry failed')))
    expect(host.textContent).toContain('manual retry failed')
    expect(host.textContent).toContain('retained sweep result')
    await act(async () => host.querySelectorAll<HTMLInputElement>('input[type="radio"]')[1].click())
    expect(pending).toHaveLength(3)
    expect(host.textContent).not.toContain('retained sweep result')
    await act(async () => pending[2].reject(new Error('reference retry failed')))
    expect(host.textContent).not.toContain('retained sweep result')
  } finally { act(() => root.unmount()); inputs.mockRestore(); sweep.mockRestore() }
})

it('resets task edits on selection and ignores late responses, including reference changes', async () => {
  localStorage.setItem('sdb.cpu.mode', JSON.stringify('sweep'))
  const inputs = vi.spyOn(cpuApi, 'inputs').mockResolvedValue({
    profiles: ['p1', 'p2'].map((id) => ({ id, scenario_ref: null, variant_ref: null, project_ref: null,
      tasks: [{ task: 'ui', cluster: 'BIG' }] })),
    topologies: [{ id: 'target', version: 1, soc_ref: 'soc-x', clusters: ['BIG'] }],
  })
  const pending: { request: CpuSweepRequest; reject: (reason: Error) => void }[] = []
  const sweep = vi.spyOn(cpuApi, 'sweep').mockImplementation((request) => new Promise((_, reject) => {
    pending.push({ request, reject })
  }))
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<CpuWhatIfPage ctx={{} as Ctx} />))
    expect(pending[0].request.cpu_profile_ref).toBe('p1')
    const growth = [...host.querySelectorAll<HTMLInputElement>('input[placeholder="1"]')].at(-1)!
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(growth, '2')
      growth.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => host.querySelectorAll<HTMLInputElement>('input[type="radio"]')[1].click())
    expect(pending[1].request.reference).toBe('eas')
    expect(pending[1].request.growth).toEqual({ ui: 2 })
    const selector = host.querySelector('select')!
    await act(async () => { selector.value = 'p2'; selector.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(pending[2].request.cpu_profile_ref).toBe('p2')
    expect(pending[2].request.growth).toEqual({})
    await act(async () => host.querySelectorAll<HTMLInputElement>('input[type="radio"]')[0].click())
    expect(pending[3].request.reference).toBe('measured')
    await act(async () => pending[3].reject(new Error('current response')))
    expect(host.textContent).toContain('current response')
    await act(async () => {
      pending[0].reject(new Error('old profile')); pending[1].reject(new Error('old profile'))
      pending[2].reject(new Error('old reference'))
    })
    expect(host.textContent).toContain('current response')
    expect(host.textContent).not.toContain('old profile')
    expect(host.textContent).not.toContain('old reference')
  } finally { act(() => root.unmount()); inputs.mockRestore(); sweep.mockRestore() }
})
