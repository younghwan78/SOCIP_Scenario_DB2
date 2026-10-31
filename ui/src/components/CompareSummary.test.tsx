import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { CompareSummary, sameSource, type ItemInfo, type MetricRow } from './CompareSummary'
import { srcLabel } from '../pages/Compare'

const items: ItemInfo[] = [{ label: 'uhd30-vdis', color: '#000', source: 'measured' }, { label: 'f1-uhd60', color: '#111', source: 'calculated' }]
const render = (metrics: MetricRow[], onUnify?: () => void) => renderToStaticMarkup(createElement(CompareSummary, { items, metrics, onUnify }))

describe('Compare headline guard (G-02)', () => {
  it('shows "출처 다름" instead of a Δ when ★ and the column come from different sources', () => {
    const html = render([{ group: 'Power', key: 'total_power_mw', label: 'Total power', unit: 'mW', values: [675.2, 933.4], sources: ['실측', 'Sim 저장'] }], () => {})
    expect(html).toContain('cs-v cs-mixed">출처 다름')
    expect(html).not.toContain('+38.2%')
    expect(html).toContain('Simulation 통일로 다시 계산')
  })
  it('a missing Total power reads 미계산 — never another Power row such as CPU 0.0', () => {
    const html = render([
      { group: 'Power', key: 'total_power_mw', label: 'Total power', unit: 'mW', values: [null, null] },
      { group: 'Power', key: 'fam_cpu', label: '구성 · CPU (SW)', unit: 'mW', values: [113.5, null], blank: [null, '미모델'] },
      { group: 'Power', key: 'fam_ip', label: '구성 · IP core', unit: 'mW', values: [130, 210] },
    ])
    expect(html).toContain('미계산')
    expect(html).not.toContain('＝+0.0')
    expect(html).toContain('미모델')
  })
  it('same-source values keep their Δ and ranking', () => {
    const html = render([{ group: 'Power', key: 'total_power_mw', label: 'Total power', unit: 'mW', values: [500, 600], sources: ['즉석 계산', '즉석 계산'] }])
    expect(html).toContain('+20.0%')
    expect(html).not.toContain('cs-mixed')
    expect(sameSource({ sources: ['실측', null] }, 1)).toBe(true)
  })
  it('labels sources so registered predictions of different cases still compare', () => {
    expect(srcLabel('등록 예측 (case-a)')).toBe(srcLabel('등록 예측 (case-b)'))
    expect(srcLabel('measured')).toBe('실측')
    expect(srcLabel('Sim evidence (저장)')).toBe(srcLabel('calculated'))
    expect(srcLabel('재계산 (즉석)')).toBe('즉석 계산')
  })
})
