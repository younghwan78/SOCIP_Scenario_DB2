// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { ConcurrentCard, ConcurrentView } from './ConcurrentCard'
import type { Ctx } from '../App'
import { memberLabel, type ConcurrentResult } from '../lib/concurrency'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

const row = (member: string, total: number, raise = 0) => ({
  member, scenario_id: member.split('/')[0], variant_id: member.split('/')[1], verdict: 'ok', fps: 30,
  total_mw: total, cpu_mw: total / 2, hw_mw: total / 4, bw_mw: total / 4, bw_mbs: 100, cpu_load: 0.2, dvfs_raise_mw: raise,
})

it('labels members without the uc- prefix and the SoC suffix', () => {
  expect(memberLabel('uc-vid-youtube-e2600/yt-1080p30-h264-sdr')).toBe('vid-youtube / yt-1080p30-h264-sdr')
})

it('shows the composed total, each member and the shared DVFS domain', () => {
  const r: ConcurrentResult = {
    members: [row('uc-vid-youtube-e2600/yt-1080p30', 128.3, 4.2), row('uc-call-voice-e2600/voice-call-volte', 46.1)],
    power: { total_mw: 178.6, cpu_mw: 87.2, hw_mw: 43.6, bw_mw: 43.6, dvfs_raise_mw: 4.2, sum_of_members_mw: 174.4 },
    bw: { total_mbs: 200, peak_upper_mbs: 260 }, cpu: { load_core_eq: 0.4 },
    shared_domains: [{ group: 'MIF', clock_mhz: 845, mv: 650, members: ['uc-vid-youtube-e2600/yt-1080p30', 'uc-call-voice-e2600/voice-call-volte'], delta_mw: 4.2, raised: [] }],
    shared_nodes: [{ node: 'abox', members: ['a', 'b'], mw: 20.5 }],
    verdict: { status: 'ok', failing_members: [], notes: ['abox: a, b가 같이 사용'] },
    limits: ['경합 미반영'], dvfs_table_refs: [],
  }
  const el = document.createElement('div')
  act(() => createRoot(el).render(<ConcurrentView r={r} />))
  const text = el.textContent ?? ''
  expect(text).toContain('합계 178.6 mW')
  expect(text).toContain('각자 합 174.4 + 공유 DVFS 4.2')
  expect(text).toContain('vid-youtube / yt-1080p30')
  expect(text).toContain('공유 DVFS MIF: 845 MHz')
  expect(text).toContain('abox: a, b가 같이 사용')
})

it('refuses to compose while the page has a changed condition', () => {
  const ctx = { catalog: [], scenario: 'uc-vid-youtube-e2600', variant: 'yt-1080p30' } as unknown as Ctx
  const el = document.createElement('div')
  act(() => createRoot(el).render(<ConcurrentCard ctx={ctx} options={{}} blocked="조건 변경 중" />))
  expect(el.querySelector('[data-testid="concurrent-blocked"]')?.textContent).toBe('조건 변경 중')
  const run = [...el.querySelectorAll('button')].find((b) => b.textContent === '합성') as HTMLButtonElement
  expect(run.disabled).toBe(true)
})
