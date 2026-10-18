// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { RiskRegisterCard } from '../src/components/RiskRegister'
import { risksApi, type Risk } from '../src/lib/reviewRisks'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

it('uses the local calendar day for due dates and sends closure evidence with the edit', async () => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-10-17T16:30:00Z'))
  const zone = vi.spyOn(Date.prototype, 'getTimezoneOffset').mockReturnValue(-540)
  const risk = { id: 'risk', label: 'R-01', seq: 1, project_ref: 'p', key: 'fps', rule: 'fps', severity: 'high', category: 'SW',
    title: 'FPS', detail: '', affected: ['v'], mitigation: null, owner: null, status: 'open', note: null,
    auto_state: 'active', trend: 'new', due_date: '2026-10-17', decision_needed: true, updated_at: '2026-10-17' } as Risk
  const list = vi.spyOn(risksApi, 'list').mockResolvedValue([risk])
  const update = vi.spyOn(risksApi, 'update').mockResolvedValue({ ...risk, status: 'closed', closure_evidence: 'capture OK', updated_at: 'new' })
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<RiskRegisterCard projectRef="p" tick={0} />))
    expect(host.textContent).toContain('기한 경과')
    expect(host.textContent).toContain('결정 필요')
    const status = host.querySelector<HTMLSelectElement>('[aria-label="R-01 상태"]')!
    const evidence = host.querySelector<HTMLInputElement>('[aria-label="R-01 종료 근거"]')!
    await act(async () => {
      status.value = 'closed'; status.dispatchEvent(new Event('change', { bubbles: true }))
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(evidence, 'capture OK')
      evidence.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => [...host.querySelectorAll('button')].find((b) => b.textContent === '저장')!.click())
    expect(update).toHaveBeenCalledWith('risk', expect.objectContaining({ status: 'closed', closure_evidence: 'capture OK', due_date: '2026-10-17' }))
  } finally {
    act(() => root.unmount()); list.mockRestore(); update.mockRestore(); zone.mockRestore(); vi.useRealTimers(); localStorage.clear()
  }
})
