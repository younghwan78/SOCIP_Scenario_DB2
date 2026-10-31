import { describe, expect, it } from 'vitest'
import { setupSteps, type SetupCounts } from './setup'

const empty: SetupCounts = { bases: 0, activeBasis: null, runs: 0, predictions: 0, variants: 75, measurements: 0, synthetic: 0, reports: 0 }
const href = (page: string, extra?: string) => `#/${page}${extra ? `?${extra}` : ''}`

describe('setupSteps (G-03 first-run checklist)', () => {
  it('points an empty project DB at the basis step first', () => {
    const s = setupSteps(empty, href)
    expect(s.map((x) => x.state)).toEqual(['next', 'todo', 'todo', 'todo', 'todo'])
    expect(s[0].href).toBe('#/predictions?bp=1')
  })
  it('a draft basis without an active one is not done', () => {
    expect(setupSteps({ ...empty, bases: 1 }, href)[0]).toMatchObject({ state: 'next', value: '1개 (active 없음)' })
  })
  it('the first unfinished step is next even when a later one is done', () => {
    const s = setupSteps({ ...empty, bases: 1, activeBasis: 'B1', measurements: 1, synthetic: 74 }, href)
    expect(s.map((x) => x.state)).toEqual(['done', 'next', 'todo', 'done', 'todo'])
    expect(s[3].value).toBe('실측 1 · 합성 74')
  })
})
