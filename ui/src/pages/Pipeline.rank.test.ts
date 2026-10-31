import { describe, expect, it } from 'vitest'
import type { Evidence, TimelineEvent } from '../lib/api'
import { rankTrace } from './Pipeline'

const ev = (node: string, frame: number | null): TimelineEvent => ({ task_id: `${node}#${frame ?? 'c'}`, node_id: node, frame_index: frame, start_ms: 0, end_ms: 1 })
const trace = (id: string, nodes: string[], frames: number, extra: TimelineEvent[] = []): Evidence =>
  ({ id, kind: 'evidence.simulation', timeline_events: [...nodes.flatMap((n) => Array.from({ length: frames }, (_, f) => ev(n, f))), ...extra] }) as Evidence

describe('Pipeline default trace', () => {
  it('prefers the trace that covers every used IP (own-cadence ABOX) over one with more frames', () => {
    const base = ['csis', 'mtnr', 'mfc_enc', 'panel']
    const older = trace('sim-baseline', base, 12)
    const withAudio = trace('sim-audio', base, 8, [ev('abox', null), ev('abox', null)])
    expect(rankTrace(withAudio)).toBeGreaterThan(rankTrace(older))
  })

  it('own-cadence events do not count as a frame; more frames wins at equal coverage', () => {
    const a = trace('a', ['mfc_dec', 'dpu'], 8, [ev('mfc_dec', null)])
    const b = trace('b', ['mfc_dec', 'dpu'], 9)
    expect(rankTrace(b)).toBeGreaterThan(rankTrace(a))
  })

  it('a trace that reaches an output still outranks a wider one that does not', () => {
    const noOut = trace('n', ['csis', 'pdp', 'byrp', 'rgbp', 'mtnr', 'msnr'], 8)
    const out = trace('o', ['csis', 'panel'], 8)
    expect(rankTrace(out)).toBeGreaterThan(rankTrace(noOut))
  })
})
