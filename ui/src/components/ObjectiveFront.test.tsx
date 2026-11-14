// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { ObjectiveFront, type ObjectivePoint, type Objectives } from './ObjectiveFront'

const point = (over: Partial<ObjectivePoint>): ObjectivePoint => ({
  key: 'low', total_mw: 1098.4, growth_fixed: 1.0, bw_mbs: 5200, iq_risk: 1, dvfs_raise: 0, delta_mw: 0, growth_at_least: 1.0, ...over,
})
const low = point({})
const mid = point({ key: 'mid', total_mw: 1127.46, growth_fixed: 1.1, dvfs_raise: 2, delta_mw: 29.11, growth_at_least: 1.1 })
const top = point({ key: 'top', total_mw: 1167.44, growth_fixed: 1.2, dvfs_raise: 2, delta_mw: 69.09, growth_at_least: 1.2, iq_risk: 3 })
const data: Objectives = { order: ['growth', 'power'], growth_target: null, target_met: null, recommended: top, min_power: low, front: [low, mid, top] }

function render(node: React.ReactElement) {
  const host = document.createElement('div')
  const root = createRoot(host)
  act(() => root.render(node))
  return { host, done: () => act(() => root.unmount()) }
}

it('states the rule, what the recommendation costs over the lowest power, and the front', () => {
  const { host, done } = render(<ObjectiveFront data={data} />)
  expect(host.textContent).toContain('추천 기준 SW 증가 여유 → 최저 power')
  expect(host.textContent).toContain('추천 1167.4 mW · SW 증가 여유 ×1.2 — 최저 power 조합(1098.4 mW · ×1.0)보다 +69.1 mW')
  const rows = [...host.querySelectorAll('tbody tr')].map((tr) => [...tr.querySelectorAll('td')].map((td) => td.textContent))
  expect(rows).toEqual([
    ['×1.0 까지', '1098.4', '—', '—', '5200', 'lossless', '최저 power'],
    ['×1.1 까지', '1127.5', '+29.1', '2 domain', '5200', 'lossless', ''],
    ['×1.2 까지', '1167.4', '+69.1', '2 domain', '5200', 'lossy', '추천'],
  ])
  expect(host.querySelectorAll('tbody td.err').length).toBe(1) // the lossy pick stands out
  done()
})

it('reports a growth target as met or missed, and a recommendation that is the lowest-power case', () => {
  const met = render(<ObjectiveFront data={{ ...data, growth_target: 1.1, target_met: true, recommended: mid }} />)
  expect(met.host.textContent).toContain('목표 SW 증가 ×1.1목표 충족')
  met.done()
  const missed = render(<ObjectiveFront data={{ ...data, growth_target: 1.5, target_met: false }} />)
  expect(missed.host.textContent).toContain('목표 SW 증가 ×1.5목표 미달')
  missed.done()
  const same = render(<ObjectiveFront data={{ ...data, order: ['iq', 'power'], recommended: low, front: [low] }} />)
  expect(same.host.textContent).toContain('추천 기준 IQ 유지 → 최저 power')
  expect(same.host.textContent).toContain('추천 조합이 최저 power 조합과 같습니다 (1098.4 mW · SW 증가 여유 ×1.0).')
  expect(same.host.querySelector('tbody tr')!.textContent).toContain('추천최저 power')
  same.done()
})

it('says so when nothing is eligible, and when no growth is absorbed', () => {
  const none = render(<ObjectiveFront data={{ ...data, recommended: null, min_power: null, front: [] }} />)
  expect(none.host.textContent).toBe('등록 가능한 조합이 없어 추천 기준을 적용하지 못했습니다.')
  none.done()
  const zero = point({ growth_fixed: 0, growth_at_least: 0 })
  const flat = render(<ObjectiveFront data={{ ...data, recommended: zero, min_power: zero, front: [zero] }} />)
  expect(flat.host.querySelector('tbody td')!.textContent).toBe('여유 없음 까지')
  flat.done()
})
