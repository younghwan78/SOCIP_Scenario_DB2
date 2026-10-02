import { describe, expect, it } from 'vitest'
import { clusterCover, parseListMap, parseNumberMap, rankTopologies } from './cpu'

describe('cpu what-if form parsing', () => {
  it('parses task=cluster lists and numeric maps', () => {
    expect(parseListMap('eis=MID_LF, MID_HF; post_irta=MID_HF\nbad')).toEqual({ eis: ['MID_LF', 'MID_HF'], post_irta: ['MID_HF'] })
    expect(parseNumberMap('eis=6; x=abc; post_irta=8.5')).toEqual({ eis: 6, post_irta: 8.5 })
  })
})

describe('topology ranking', () => {
  const legacy = { id: 'pmp-v1', version: 1, soc_ref: 'e2600', clusters: ['little', 'mid', 'big', 'prime'] }
  const v2 = { id: 'pmp-v2', version: 2, soc_ref: 'e2600', clusters: ['MID_LF0', 'MID_LF1', 'MID_HF', 'BIG'] }
  const prof = { id: 'p', scenario_ref: null, variant_ref: null, project_ref: null, tasks: [{ task: 'a', cluster: 'MID_HF' }, { task: 'b', cluster: 'BIG' }] }
  it('prefers the topology covering the measured clusters', () => {
    expect(clusterCover(v2, prof)).toBe(1)
    expect(clusterCover(legacy, prof)).toBe(0)
    expect(rankTopologies([legacy, v2], prof)[0].id).toBe('pmp-v2')
  })
  it('falls back to newest version without task clusters', () => {
    expect(rankTopologies([legacy, { ...v2, clusters: ['x'] }], undefined)[0].id).toBe('pmp-v2')
  })
})
