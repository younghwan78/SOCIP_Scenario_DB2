import { expect, it } from 'vitest'
import { idleColumns } from './columnPolicy'
import { measCellKey, type Coverage } from './calibration'
import type { Column } from '../components/DataTable'

interface R { id: string; pw: number | null; llc: string; res: string }
const rows: R[] = [{ id: 'a', pw: null, llc: '4 MB', res: 'UHD' }, { id: 'b', pw: null, llc: '4 MB', res: '8K' }]
const col = (key: keyof R): Column<R> => ({ key, label: key, sort: (r) => r[key], render: () => null })

it('finds all-empty and single-value columns among the policy keys (G-07)', () => {
  const idle = idleColumns([col('id'), col('pw'), col('llc'), col('res')], rows, ['pw', 'llc', 'res'], (c) => String(c.label))
  expect(idle).toEqual([
    { key: 'pw', label: 'pw', kind: 'empty', value: null },
    { key: 'llc', label: 'llc', kind: 'constant', value: '4 MB' },
  ])
  // one row has no comparison to make: a value is not "constant" there
  expect(idleColumns([col('llc')], rows.slice(0, 1), ['llc'], (c) => String(c.label))).toEqual([])
})

it('compares what the cell shows when the sort key does not determine it (same measured date, different power)', () => {
  const at = '2026-10-01T10:00:00'
  const cov = (mw: number): Coverage => ({ simulation: 0, measurement: 1, synthetic: 0, current_prediction: null,
    measurements: [{ id: `m${mw}`, at, origin: 'physical_capture', synthetic: false, total_mw: mw, shown: true }] })
  const covs: Record<string, Coverage> = { a: cov(500), b: cov(900) }
  const meas: Column<R> = { key: 'meas', label: '실측', sort: () => `1${at}`, render: () => null }
  expect(idleColumns([meas], rows, ['meas'], (c) => String(c.label))).toHaveLength(1)          // sort key alone: constant
  expect(idleColumns([meas], rows, ['meas'], (c) => String(c.label), { meas: (r) => measCellKey(covs[r.id]) })).toEqual([])
  expect(measCellKey(covs.a)).toBe('10/01 · 500')
  expect(measCellKey(undefined)).toBeNull()
})
