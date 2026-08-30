import { describe, expect, it } from 'vitest'
import { formatMs, numeric } from '../src/engine/format'

describe('formatMs (parity with timing_chart.format_ms)', () => {
  it('formats numbers with trimmed trailing zeros', () => {
    expect(formatMs(1.5)).toBe('1.5 ms')
    expect(formatMs(2)).toBe('2 ms')
    expect(formatMs(0.1234)).toBe('0.123 ms')
    expect(formatMs('3.100')).toBe('3.1 ms')
  })

  it('renders dash for missing values', () => {
    expect(formatMs(null)).toBe('-')
    expect(formatMs(undefined)).toBe('-')
    expect(formatMs('abc')).toBe('-')
  })
})

describe('numeric', () => {
  it('coerces numeric strings and rejects garbage', () => {
    expect(numeric('4.2')).toBe(4.2)
    expect(numeric(7)).toBe(7)
    expect(numeric('x')).toBeNull()
    expect(numeric(null)).toBeNull()
  })
})
