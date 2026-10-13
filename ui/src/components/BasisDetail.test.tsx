// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, expect, it, vi } from 'vitest'
import { BasisDetailBody, BasisInfoButton } from './BasisDetail'
import { basisApi, type BasisDetail } from '../lib/basis'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
afterEach(() => vi.restoreAllMocks())
const detail = {
  basis: { id: 'basis-p-1', code: 'B1', status: 'active', components: 'cfg v1', content_hash: 'abc', engine_rev: 'engine/1' },
  parent: null, inputs: { current: false, changed: ['config_profile'], engine_now: 'engine/1' },
  profile: { id: 'cfg', version: 2, status: 'draft', run_config: { include_cpu_power: false } },
  power_params: null, dvfs: null, predictions: { current: 0, ad_hoc: 0, scenarios: 0 },
} as BasisDetail

it('distinguishes changed catalog details from the original basis and excluded CPU power', () => {
  const html = renderToStaticMarkup(<BasisDetailBody d={detail} overrides={['config']} />)
  expect(html).toContain('현재 DB 값')
  expect(html).toContain('제외')
  expect(html).toContain('B1*')
  expect(html).not.toContain('가정값 (flat)')
})

it('loads details on opening and closes with Escape', async () => {
  const fetchDetail = vi.spyOn(basisApi, 'detail').mockResolvedValue(detail)
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<BasisInfoButton basisId="basis-p-1" label="B1" />))
    expect(fetchDetail).not.toHaveBeenCalled()
    await act(async () => host.querySelector<HTMLButtonElement>('button')!.click())
    expect(fetchDetail).toHaveBeenCalledWith('basis-p-1')
    expect(host.querySelector('[role="dialog"]')?.textContent).toContain('현재 DB 값')
    act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    expect(host.querySelector('[role="dialog"]')).toBeNull()
  } finally { act(() => root.unmount()) }
})
