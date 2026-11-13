// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { DesignAxesTable, SearchCoverage, type DesignAxes, type DesignAxisResult } from './DesignAxes'

const row = (over: Partial<DesignAxisResult>): DesignAxisResult => ({
  key: 'fps=24', labels: ['FPS 24 fps'], iq: 'neutral', spec_ok: true, spec_reasons: [], verdict: 'ok', fps: 24,
  total_mw: 607.39, delta_mw: -151.05, delta_pct: -19.92, bw_mbs: 3000, delta_bw_mbs: -700,
  raw_total_mw: 635.7, raw_delta_mw: -158.13, raw_delta_pct: -19.9, ...over,
})
const data: DesignAxes = {
  status: 'ok', sets: 3, max_sets: 64, cases: 12, notes: [],
  dimensions: [{ lever: 'fps', label: 'FPS', selector: null, group: 'temporal', values: ['24 fps', '60 fps'] },
    { lever: 'power_knob', label: 'Power option · pyramid_l0', selector: 'pyramid_l0', group: 'temporal', values: ['skip'] }],
  results: [
    row({}),
    row({ key: 'power_knob[pyramid_l0]=skip', labels: ['Power option · pyramid_l0 skip'], iq: 'eval', lever_iq: 'eval', fps: 30, total_mw: 740, delta_mw: -18.4, delta_pct: -2.4, lever_notes: ['pyramid L0 skip'] }),
    row({ key: 'fps=60', labels: ['FPS 60 fps'], spec_ok: false, verdict: 'fail', spec_reasons: ['no eligible combination'], fps: 60, total_mw: null, delta_mw: null, delta_pct: null, delta_bw_mbs: null, raw_delta_mw: 790.66, raw_delta_pct: 104.2 }),
  ],
  errors: [{ key: 'chain_size[nope]=1920x1080', error: 'nope: no processing size to crop/scale from' }],
}

function render(node: React.ReactElement) {
  const host = document.createElement('div')
  const root = createRoot(host)
  act(() => root.render(node))
  return { host, done: () => act(() => root.unmount()) }
}

it('lists every lever combination against the variant, with what to check before using it', () => {
  const { host, done } = render(<DesignAxesTable data={data} baseMw={758.44} />)
  const rows = [...host.querySelectorAll('tbody tr')].map((tr) => [...tr.querySelectorAll('td')].map((td) => td.textContent))
  expect(rows[0].slice(0, 5)).toEqual(['FPS 24 fps', 'OK', '24', '607.4', '-151.1 (-19.9%)'])
  expect(rows[1][0]).toBe('Power option · pyramid_l0 skippyramid L0 skip')
  expect(rows[1][7]).toBe('레버 IQ 평가 필요')
  expect(rows[2].slice(3, 5)).toEqual(['—', '—'])
  expect(rows[2][6]).toBe('+790.7 (+104.2%)')
  expect(rows[2][7]).toBe('no eligible combination')
  expect(host.textContent).toContain('FPS: 24 fps / 60 fps · Power option · pyramid_l0: skip · 3 조합 · 기준 = 이 variant의 추천 조합 758.4 mW')
  // combinations this variant cannot take are listed, not hidden
  expect(host.querySelector('details summary')!.textContent).toBe('이 variant에 적용하지 못한 조합 1개')
  expect(host.querySelector('details li')!.textContent).toContain('chain_size[nope]=1920x1080 — nope: no processing size')
  expect(host.textContent).toContain('추천하지 않으며')
  done()
})

it('warns when the shown power rests on lossy compression, whatever the levers need', () => {
  const lossy = { ...data, errors: [], results: [
    row({ iq: 'trade', lever_iq: 'neutral', lossy: true }),
    row({ key: 'k2', iq: 'trade', lever_iq: 'eval', lossy: true }),
    row({ key: 'k3', iq: 'trade', lever_iq: 'trade', lossy: false }),
    row({ key: 'k4', iq: 'neutral' })] }
  const { host, done } = render(<DesignAxesTable data={lossy} baseMw={758.44} />)
  const cautions = [...host.querySelectorAll('tbody tr')].map((tr) => tr.querySelectorAll('td')[7].textContent)
  expect(cautions).toEqual([
    'lossy 압축 선택 (화질 trade) — 표시 전력은 손실 압축 기준',
    '레버 IQ 평가 필요 · lossy 압축 선택 (화질 trade) — 표시 전력은 손실 압축 기준',
    '레버 화질 trade', '—'])
  done()
})

it('says whether every combination was explored, and which levers were only tried alone', () => {
  const full = render(<SearchCoverage search={{ mode: 'exhaustive', full_factorial: 23, one_at_a_time: 5, combined: 18 }} evaluated={23} />)
  expect(full.host.textContent).toBe('전수 탐색 레버 조합 23개를 모두 탐색')
  full.done()
  const part = render(<SearchCoverage evaluated={7} search={{ mode: 'screened', full_factorial: 23, one_at_a_time: 5, combined: 2, ranking: [
    { lever: 'fps', label: 'FPS', impact_mw: 790.66, impact_pct: 104.2, combined: true },
    { lever: 'llc_alloc', label: 'LLC 할당 · PYRAMID_L0', impact_mw: 26.98, impact_pct: 3.6, combined: true },
    { lever: 'history_interval', label: 'Previous DMA 빈도 · TNR_PREV_L0', impact_mw: 20.2, impact_pct: null, combined: false },
    { lever: 'chain_size', label: 'IP crop · downscale · nope', impact_mw: null, impact_pct: null, combined: false }] }} />)
  expect(part.host.textContent).toContain('부분 탐색 전체 23 조합 중 7개 탐색 — 값 하나씩 5개 + 영향이 큰 레버끼리 조합 2개. 탐색하지 않은 조합에 더 낮은 전력이 있을 수 있습니다.')
  expect([...part.host.querySelectorAll('li')].map((li) => li.textContent)).toEqual([
    'FPS 단독 영향 최대 ±790.7 mW (104.2%)조합 포함', 'LLC 할당 · PYRAMID_L0 단독 영향 최대 ±27.0 mW (3.6%)조합 포함',
    'Previous DMA 빈도 · TNR_PREV_L0 단독 영향 최대 ±20.2 mW단독만', 'IP crop · downscale · nope 단독 결과 없음단독만'])
  part.done()
  const none = render(<SearchCoverage evaluated={5} search={{ mode: 'screened', full_factorial: 23, one_at_a_time: 5, combined: 0, ranking: [
    { lever: 'fps', label: 'FPS', impact_mw: null, impact_pct: null, combined: false }] }} />)
  expect(none.host.textContent).toContain('(조합은 탐색하지 않음)')
  expect(none.host.textContent).toContain('순위를 매기지 못했습니다 (이 variant에 적용할 수 없거나 case 예산 소진')
  expect(none.host.querySelector('ol')).toBeNull()
  none.done()
  // the table shows it above the rows
  const table = render(<DesignAxesTable data={{ ...data, search: { mode: 'exhaustive', full_factorial: 3, one_at_a_time: 3, combined: 0 } }} baseMw={758.44} />)
  expect(table.host.querySelector('.dax-search')!.textContent).toContain('전수 탐색')
  table.done()
})

it('says so when the variant has no recommended case to compare with, or nothing applied', () => {
  const none = render(<DesignAxesTable data={{ ...data, results: [], status: 'failed' }} baseMw={null} />)
  expect(none.host.querySelector('table')).toBeNull()
  expect(none.host.textContent).toContain('추천 조합이 없어 Δ는 압축 전 기준만 표시')
  expect(none.host.querySelector('details summary')!.textContent).toContain('1개')
  none.done()
})
