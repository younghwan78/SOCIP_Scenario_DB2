// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { BasisPanel } from './BasisPanel'
import { basisApi, type ModelBasis, type Trial } from '../lib/basis'
import { setApiCredential } from '../lib/auth'

vi.mock('../lib/api', () => ({ api: { simConfigs: async () => ({ items: [] }) } }))
vi.mock('../lib/calibration', () => ({ calibrationApi: { powerParams: async () => [] } }))
vi.mock('../lib/library', () => ({ libraryApi: { dvfs: async () => ({ items: [] }) } }))
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
afterEach(() => { vi.restoreAllMocks(); setApiCredential(null) })

const basis = { id: 'basis-p-1', code: 'B1', project_ref: 'p', status: 'draft', components: 'code defaults' } as ModelBasis
const trial: Trial = { basis, against: null, diff: [], items: [], summary: {
  total: 0, done: 0, skipped: 0, failed: 0, delta_mw_sum: null, delta_mw_min: null, delta_mw_max: null,
  started_at: null, promoted_at: null,
} }
const button = (host: HTMLElement, text: string) => [...host.querySelectorAll('button')].find((b) => b.textContent?.includes(text))!
function setup() {
  vi.spyOn(basisApi, 'list').mockResolvedValue({ items: [basis], active: null })
  vi.spyOn(basisApi, 'trial').mockResolvedValue(trial)
  const tryOne = vi.spyOn(basisApi, 'tryOne')
  let finish!: (value: Trial) => void
  const start = vi.spyOn(basisApi, 'startTrial').mockReturnValue(new Promise((resolve) => { finish = resolve }))
  return { start, tryOne, finish: (value: Trial) => finish(value) }
}

it('starts only one trial when clicked twice before the response', async () => {
  const mock = setup(), host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<BasisPanel project="p" onDone={() => {}} onClose={() => {}} />))
    const start = button(host, '시험 계산 시작')
    act(() => { start.click(); start.click() })
    expect(mock.start).toHaveBeenCalledTimes(1)
    await act(async () => mock.finish(trial))
  } finally { act(() => root.unmount()) }
})

it('does not queue trial calculations after switching the acting credential', async () => {
  const mock = setup(), host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<BasisPanel project="p" onDone={() => {}} onClose={() => {}} />))
    act(() => button(host, '시험 계산 시작').click())
    await act(async () => setApiCredential({ keyId: 'new-actor', secret: 'test-secret' }))
    await act(async () => mock.finish({ ...trial, items: [{ prediction_id: 'p1', scenario_id: 's', variant_id: 'v',
      status: 'pending', old_total_mw: null }] }))
    expect(mock.tryOne).not.toHaveBeenCalled()
  } finally { act(() => root.unmount()) }
})
