import { describe, expect, it } from 'vitest'
import { chosenKeys, pathRows } from './LeverAnalysis'
import type { LeverAnalysis, LeverStep } from '../lib/archExplore'

const steps: LeverStep[] = [
  { phase: 'baseline', label: 'baseline', iq: 'neutral', delta_mw: 0, total_mw: 100, bw_mbs: 1000 },
  { phase: 'neutral', label: 'L0 lossless', lever: 'comp:L0=COMP_YUV_LOSSLESS', iq: 'neutral', delta_mw: -10, total_mw: 90, bw_mbs: 900 },
  { phase: 'eval', label: 'L0 skip', lever: 'knob:l0=skip', iq: 'eval', delta_mw: -20, total_mw: 70, bw_mbs: 700, dropped: ['L0'] },
  { phase: 'trade', label: 'L1 lossy', lever: 'comp:L1=COMP_YUV_LOSSY', iq: 'trade', delta_mw: -5, total_mw: 65, bw_mbs: 650 },
]

describe('lever path', () => {
  it('inserts a milestone total after each phase and notes dropped compression', () => {
    const rows = pathRows(steps)
    expect(rows.map((r) => r.label)).toEqual(['baseline', 'L0 lossless', '= 화질 무손실 최적', 'L0 skip', '= + IQ 평가 lever', 'L1 lossy', '= + lossy'])
    expect(rows[3]).toMatchObject({ start: 90, end: 70, kind: 'eval' })
    expect(rows[3].note).toContain('L0')
    expect(rows[6]).toMatchObject({ kind: 'total', end: 65 })
  })
  it('marks levers of the IQ-keeping end state and the lossy step as chosen', () => {
    const la: LeverAnalysis = {
      status: 'ok',
      levers: [
        { key: 'comp:L1=COMP_YUV_LOSSLESS', kind: 'compression', buffer: 'L1', mode: 'COMP_YUV_LOSSLESS', label: 'L1 lossless', iq: 'neutral', confidence: 'typical', alone: null, in_context: null, overlap: false },
        { key: 'knob:l0=skip', kind: 'option', label: 'L0 skip', iq: 'eval', confidence: 'model', alone: null, in_context: null, overlap: false },
        { key: 'comp:L1=COMP_YUV_LOSSY', kind: 'compression', buffer: 'L1', mode: 'COMP_YUV_LOSSY', label: 'L1 lossy', iq: 'trade', confidence: 'catalog', alone: null, in_context: null, overlap: false },
      ],
      milestones: {
        eval: { total_mw: 70, bw_mbs: 0, delta_mw: -30, delta_pct: -30, options: ['L0 skip'], compression: { L1: 'COMP_YUV_LOSSLESS' } },
        trade: { total_mw: 65, bw_mbs: 0, delta_mw: -35, delta_pct: -35, options: ['L0 skip'], compression: { L1: 'COMP_YUV_LOSSY' } },
      },
    }
    expect([...chosenKeys(la)].sort()).toEqual(['comp:L1=COMP_YUV_LOSSLESS', 'comp:L1=COMP_YUV_LOSSY', 'knob:l0=skip'])
  })
})
