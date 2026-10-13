// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { LeverSelect } from '../src/components/LeverSelect'
import { archApi, type LeverAnalysis, type LeverRegisterResult } from '../src/lib/archExplore'
import { DEFAULT_BATTERY } from '../src/lib/battery'
import { ApiError } from '../src/lib/api'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

it('registers one prediction for rapid repeated clicks and blocks an ineligible point', async () => {
  const reviews = vi.spyOn(archApi, 'optionReviews').mockResolvedValue([])
  const board = vi.spyOn(archApi, 'board').mockResolvedValue({ rows: [] })
  let finish!: (r: LeverRegisterResult) => void
  const register = vi.spyOn(archApi, 'registerLever').mockImplementation(() => new Promise((resolve) => { finish = resolve }))
  const point = { options: [], option_keys: [], comp: {}, iq: 'neutral' as const, total_mw: 100, bw_mbs: 0, cpu_mw: 50, hw_mw: 50, bw_mw: 0, eligible: true }
  const la: LeverAnalysis = { status: 'ok', baseline: { ...point }, points: [point], levers: [] }
  const host = document.createElement('div'), root = createRoot(host)
  const props = { la, battery: DEFAULT_BATTERY, runId: 'run-1', scenarioId: 'scenario', variantId: 'variant', projectRef: 'project', readOnly: false, sel: { options: [], comp: {} }, setSel: vi.fn() }
  try {
    await act(async () => root.render(<LeverSelect {...props} />))
    const button = host.querySelector<HTMLButtonElement>('button.primary')!
    await act(async () => { button.click(); button.click() })
    expect(register).toHaveBeenCalledTimes(1)
    expect(register.mock.calls[0][0].expected_current).toEqual([{ scenario_id: 'scenario', variant_id: 'variant', prediction_id: null }])
    expect(host.querySelector('fieldset')!.disabled).toBe(true)
    await act(async () => finish({ status: 'registered', rule: 'lever:iq-keep', run_id: 'run-1', promoted: [{ id: 'prediction', total_mw: 100 }] }))
    expect(host.textContent).toContain('prediction')
    await act(async () => root.render(<LeverSelect {...props} la={{ ...la, points: [{ ...point, eligible: false }] }} />))
    expect(host.querySelector<HTMLButtonElement>('button.primary')!.disabled).toBe(true)
    expect(host.textContent).toContain('탐색 제약을 만족하지 않아')
  } finally {
    await act(async () => root.unmount())
    reviews.mockRestore(); register.mockRestore(); board.mockRestore()
  }
})

it('requires explicit current-basis refresh after a registration conflict', async () => {
  const reviews = vi.spyOn(archApi, 'optionReviews').mockResolvedValue([])
  const board = vi.spyOn(archApi, 'board').mockResolvedValue({ rows: [] })
  const register = vi.spyOn(archApi, 'registerLever').mockRejectedValue(new ApiError('changed', 409))
  const point = { options: [], option_keys: [], comp: {}, iq: 'neutral' as const, total_mw: 100, bw_mbs: 0, cpu_mw: 50, hw_mw: 50, bw_mw: 0, eligible: true }
  const la: LeverAnalysis = { status: 'ok', baseline: { ...point }, points: [point], levers: [] }
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<LeverSelect la={la} battery={DEFAULT_BATTERY} runId="run" scenarioId="s" variantId="v" projectRef="p" readOnly={false} sel={{ options: [], comp: {} }} setSel={() => {}} />))
    await act(async () => host.querySelector<HTMLButtonElement>('button.primary')!.click())
    expect(host.textContent).toContain('기준 예측이 변경되었습니다')
    expect(host.querySelector<HTMLButtonElement>('button.primary')!.disabled).toBe(true)
    await act(async () => [...host.querySelectorAll('button')].find((button) => button.textContent === '기준 다시 확인')!.click())
    expect(board).toHaveBeenCalledTimes(2)
    expect(host.querySelector<HTMLButtonElement>('button.primary')!.disabled).toBe(false)
    expect(register).toHaveBeenCalledTimes(1)
  } finally { act(() => root.unmount()); reviews.mockRestore(); board.mockRestore(); register.mockRestore() }
})
