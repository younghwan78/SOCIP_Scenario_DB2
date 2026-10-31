import { expect, it } from 'vitest'
import { idleColumns } from './columnPolicy'
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
