// @vitest-environment jsdom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it } from 'vitest'
import { StrategyCard } from './RebalanceView'
import { bigVerdict, strategyVerdict, type CpuRebalance, type RbStrategies, type RbStrategyRow } from '../lib/rebalance'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const row = (clusters: string[], mw: number, feasible = true): RbStrategyRow => ({
  kind: clusters.length === 1 ? 'concentrate' : 'spread', clusters, ways: clusters.length, total_mw: mw, delta_mw: mw - 450, feasible,
  mhz: { MID_LF0: 1000, MID_LF1: 400, MID_HF: 600, dsu: 645 }, mw: {}, assign: { eis: clusters[0] }, moved: [], min_slack_ms: 1.2,
})
const strat = (over: Partial<RbStrategies> = {}): RbStrategies => ({
  rows: [row(['MID_LF0'], 503), row(['MID_HF'], 520, false), row(['MID_LF0', 'MID_LF1'], 333), row(['MID_LF0', 'MID_LF1', 'MID_HF'], 282)],
  best_concentrate: row(['MID_LF0'], 503), best_spread: row(['MID_LF0', 'MID_LF1', 'MID_HF'], 282), winner: 'spread', spread_gain_mw: 221, complete: true,
  big_check: { clusters: ['BIG'], base_mw: 282, base_assign: {}, best: { unit: 'post_crta', cluster: 'BIG', total_mw: 284, delta_mw: 1.9, feasible: true, mhz: 1000, dsu_mhz: 645 },
    moves: [{ unit: 'post_crta', cluster: 'BIG', total_mw: 284, delta_mw: 1.9, feasible: true, mhz: 1000, dsu_mhz: 645 }], gain: false },
  ...over,
})

describe('MID concentrate vs spread', () => {
  it('verdicts', () => {
    expect(strategyVerdict(strat()).text).toContain('분산이 유리')
    expect(strategyVerdict(strat({ winner: 'concentrate', spread_gain_mw: -12 })).text).toContain('집중이 유리')
    expect(strategyVerdict(strat({ best_concentrate: null, best_spread: null, winner: 'none' })).tone).toBe('warn')
    expect(bigVerdict(strat().big_check!).text).toContain('BIG 사용 이득 없음')
    expect(bigVerdict({ ...strat().big_check!, gain: true, best: { ...strat().big_check!.best!, delta_mw: -5 } }).tone).toBe('warn')
  })
  it('renders groups, marks infeasible and pins a strategy', () => {
    const picked: Record<string, string>[] = []
    const r = { pool: ['MID_LF0', 'MID_LF1', 'MID_HF'], symmetric: [['MID_LF0', 'MID_LF1']], reference: { total_mw: 450 }, strategies: strat() } as unknown as CpuRebalance
    const host = document.createElement('div'); document.body.appendChild(host)
    const root = createRoot(host)
    act(() => root.render(createElement(StrategyCard, { r, onPickCase: (a: Record<string, string>) => picked.push(a) })))
    expect(host.textContent).toContain('집중 (한 cluster)')
    expect(host.textContent).toContain('BIG 사용 이득 없음')
    expect(host.textContent).toContain('MID_LF0 ≡ MID_LF1')
    expect(host.querySelectorAll('.rb-strat-row.infeasible').length).toBe(1)
    act(() => (host.querySelectorAll('.rb-strat-row')[3] as HTMLButtonElement).click())
    act(() => ([...host.querySelectorAll('button')].find((b) => b.textContent?.includes('이 배치 고정')) as HTMLButtonElement).click())
    expect(picked).toEqual([{ eis: 'MID_LF0' }])
    act(() => root.unmount())
  })
})
