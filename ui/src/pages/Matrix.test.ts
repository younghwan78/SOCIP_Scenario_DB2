import { expect, it } from 'vitest'
import { provenanceText } from './Matrix'
import type { BoardRow, FreshRow } from '../lib/archExplore'

const row = { run_id: 'r', selection_rule: 'auto:min-power-iq' } as BoardRow
it('ranks prediction provenance: unregistered > stale > measured > prediction only (MAT-02)', () => {
  expect(provenanceText(undefined).text).toBe('미등록')
  expect(provenanceText({ row, fresh: { status: 'stale', reasons: ['variant_doc'] } as FreshRow, measured: 2 }).text).toBe('입력 변경')
  expect(provenanceText({ row, fresh: null, measured: 2 }).text).toBe('실측 2')
  expect(provenanceText({ row, fresh: null, measured: 0 }).text).toBe('예측만')
})
