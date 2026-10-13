import { expect, it } from 'vitest'
import { currentGuards } from './registration'
import type { BoardRow } from './archExplore'
it('guards every scenario/variant pair and represents a first registration as null', () => {
  const rows = [{ id: 'p1', scenario_id: 's1', variant_id: 'same' }, { id: 'p2', scenario_id: 's2', variant_id: 'same' }] as BoardRow[]
  expect(currentGuards([{ scenario_id: 's2', variant_id: 'same' }, { scenario_id: 's3', variant_id: 'new' }], rows)).toEqual([
    { scenario_id: 's2', variant_id: 'same', prediction_id: 'p2' }, { scenario_id: 's3', variant_id: 'new', prediction_id: null },
  ])
})
