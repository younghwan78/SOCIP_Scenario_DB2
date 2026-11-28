import { describe, expect, it } from 'vitest'
import budget from './styleBudget.json'

/** X-08 (U-06 follow-up): inline styles and colour literals may only go down. Each .tsx file has a ceiling of
 * ``style={{`` occurrences (a new file: 0) and the colour literals of all .tsx files have one total ceiling.
 * After moving styles to classes / tokens, lower the numbers in styleBudget.json (the failure message prints
 * the current counts). */
const files = import.meta.glob('./**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>
const source = Object.entries(files).filter(([p]) => !p.includes('.test.'))

const count = (text: string, re: RegExp) => (text.match(re) ?? []).length
const INLINE = /style=\{\{/g
const COLOUR = /#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b/g

describe('style budget (X-08)', () => {
  it('no file adds inline styles', () => {
    const over = source.map(([p, t]) => [p.replace(/^\.\//, ''), count(t, INLINE)] as const)
      .filter(([p, n]) => n > ((budget.inline as Record<string, number>)[p] ?? 0))
    expect(over, `inline style ceiling exceeded (style={{ count): ${JSON.stringify(Object.fromEntries(over))}`).toEqual([])
  })
  it('colour literals do not grow', () => {
    const total = source.reduce((n, [, t]) => n + count(t, COLOUR), 0)
    expect(total, `colour literals in .tsx: ${total} (ceiling ${budget.colour_literals})`).toBeLessThanOrEqual(budget.colour_literals)
  })
})
