import { describe, expect, it } from 'vitest'
import type { HandoffDoc, TimelineEvent } from './api'
import { cadenceLinks, cadencePeriod, deriveHandoff, fmtHz, layoutFlow, layoutFlows } from './handoff'
import { buildTimeline, FULLSTACK_GROUPS } from './timeline'

// camera-like unit: request issued 4 frames ahead, ISP, a 5th-frame VPS step, then preview / encode branches
const doc: HandoffDoc = {
  format: 'sdb.handoff/1',
  participants: [
    { id: 'fwk.cs', layer: 'framework', name: 'cameraserver' },
    { id: 'fwk.sf', layer: 'framework', name: 'surfaceflinger' },
    { id: 'hal.cam', layer: 'hal', name: 'camera.provider' },
    { id: 'hw.isp', layer: 'hw', name: 'ISP' },
    { id: 'hw.vps', layer: 'hw', name: 'VPS' },
    { id: 'hw.dpu', layer: 'hw', name: 'DPU' },
    { id: 'hw.mfc', layer: 'hw', name: 'MFC' },
    { id: 'hw.abox', layer: 'hw', name: 'ABOX' },
    { id: 'hal.aud', layer: 'hal', name: 'audio HAL' },
  ],
  cadences: [
    { id: 'frame', name: 'Sensor frame', kind: 'frame', period_ms: 100 / 3 },
    { id: 'vsync', name: 'Display vsync', kind: 'vsync', period_ms: 1000 / 60 },
    { id: 'od', name: 'VPS OD', kind: 'divided', of: 'frame', every: 5 },
    { id: 'abox', name: 'ABOX period', kind: 'period', period_ms: 20 },
    { id: 'touch', name: 'Touch', kind: 'event' },
  ],
  flows: [
    { id: 'frame', name: 'Sensor frame', cadence: 'frame', steps: [
      { to: 'fwk.cs', call: 'processCaptureRequest', frame_offset: -4, t_ms: 0, dur_ms: 0.3 },
      { from: 'fwk.cs', to: 'hal.cam', call: 'request', handoff: 'ipc', frame_offset: -4, t_ms: 0.4, dur_ms: 2 },
      { from: 'hal.cam', to: 'hw.isp', call: 'SOF', handoff: 'kick', t_ms: 133.3, dur_ms: 10 },
      { from: 'hw.isp', to: 'hw.vps', call: 'OD', cadence: 'od', every: 5, t_ms: 144, dur_ms: 1.8 },
      { from: 'hw.isp', to: 'hal.cam', call: 'EIS', handoff: 'complete', t_ms: 146, dur_ms: 7.8 },
      { note: '갈라짐', over: ['fwk.sf'] },
      { from: 'hal.cam', to: 'fwk.sf', call: 'queueBuffer', branch: 'preview', t_ms: 155, dur_ms: 1.4 },
      { from: 'fwk.sf', to: 'hw.dpu', call: 'scanout', cadence: 'vsync', branch: 'preview', t_ms: 170, dur_ms: 15.5 },
      { from: 'hal.cam', to: 'hw.mfc', call: 'encode', handoff: 'kick', branch: 'encode', t_ms: 154, dur_ms: 7.5 },
    ] },
    { id: 'audio', name: 'Audio period', cadence: 'abox', steps: [
      { to: 'hw.abox', call: 'capture', t_ms: 0, dur_ms: 0.8 },
      { from: 'hw.abox', to: 'hal.aud', call: 'read', handoff: 'irq', t_ms: 0.9, dur_ms: 0.2 },
    ] },
  ],
}

describe('hand-off flow layout', () => {
  it('resolves divided and event cadences', () => {
    expect(cadencePeriod(doc, 'od')).toBeCloseTo(500 / 3)
    expect(fmtHz(cadencePeriod(doc, 'od'))).toBe('6 Hz')
    expect(cadencePeriod(doc, 'touch')).toBeNull()
    expect(fmtHz(null)).toBe('비주기')
  })

  it('layer mode gives the six-lane mockup columns, participant mode one per process', () => {
    const byLayer = layoutFlow(doc, doc.flows[0], 'layer')
    expect(byLayer.columns.map((c) => c.id)).toEqual(['framework', 'hal', 'hw'])
    expect(byLayer.columns[0].title).toBe('cameraserver · surfaceflinger')
    expect(byLayer.columns[2].title).toBe('ISP · VPS')
    expect(byLayer.columns[2].sub).toBe('+ DPU · MFC')
    const byPart = layoutFlow(doc, doc.flows[0], 'participant')
    expect(byPart.columns.map((c) => c.id)).toEqual(['fwk.cs', 'fwk.sf', 'hal.cam', 'hw.isp', 'hw.vps', 'hw.dpu', 'hw.mfc'])
    // ABOX belongs to another flow: not a column here
    expect(byPart.columns.some((c) => c.id === 'hw.abox')).toBe(false)
  })

  it('numbers calls, keeps notes unnumbered and marks off-rate steps', () => {
    const lay = layoutFlow(doc, doc.flows[0], 'participant')
    const calls = lay.rows.filter((r) => r.kind === 'call')
    expect(calls.map((r) => r.n)).toEqual([1, 2, 3, 4, 5, 6, 7, 8])
    const badges = Object.fromEntries(calls.map((r) => [r.step.call, r.badges.map((b) => b.text)]))
    expect(badges.processCaptureRequest).toEqual(['n−4 단위 앞'])
    expect(badges.OD).toEqual(['↻ VPS OD · 6 Hz'])
    expect(badges.scanout).toEqual(['↻ Display vsync · 60 Hz'])
    expect(calls.find((r) => r.step.call === 'SOF')!.from).toBe(2)
    expect(calls[0].from).toBeNull()
  })

  it('wait Δ is measured from the call that last ended on the caller', () => {
    const calls = layoutFlow(doc, doc.flows[0], 'layer').rows.filter((r) => r.kind === 'call')
    const w = Object.fromEntries(calls.map((r) => [r.step.call, r.wait]))
    expect(w.request).toBeCloseTo(0.1)            // 0.4 − (0 + 0.3)
    expect(w.SOF).toBeCloseTo(130.9)              // 133.3 − (0.4 + 2): the n−4 lead
    expect(w.queueBuffer).toBeCloseTo(1.2)        // 155 − (146 + 7.8)
    expect(w.processCaptureRequest).toBeNull()
  })

  it('a note joins the branch block it precedes; branches become one par block with segments', () => {
    const lay = layoutFlow(doc, doc.flows[0], 'layer')
    const pars = lay.frames.filter((f) => f.kind === 'par')
    expect(pars).toHaveLength(1)
    expect(lay.rows[pars[0].start].kind).toBe('note')
    expect(pars[0].segments!.map((s) => s.label)).toEqual(['preview', 'encode'])
    expect(pars[0].end).toBe(lay.rows.length - 1)
  })

  it('steps on another cadence form a sub-loop frame; a single flow has no outer loop frame', () => {
    const lay = layoutFlow(doc, doc.flows[0], 'layer')
    const subs = lay.frames.filter((f) => f.kind === 'sub')
    expect(subs.map((f) => [f.cadence, lay.rows[f.start].step.call, f.tag])).toEqual([
      ['od', 'OD', 'every 5th Sensor frame'], ['vsync', 'scanout', 'vsync loop']])
    expect(lay.frames.some((f) => f.kind === 'loop')).toBe(false)
  })

  it('all loops: every flow in its own loop frame on shared columns, numbering continues', () => {
    const lay = layoutFlows(doc, doc.flows, 'layer')
    const loops = lay.frames.filter((f) => f.kind === 'loop')
    expect(loops.map((f) => [f.label, f.tag])).toEqual([['Sensor frame · 30 Hz', 'frame loop'], ['Audio period · 50 Hz', 'independent loop']])
    expect(loops[1].start).toBe(loops[0].end + 1)
    expect(lay.columns.map((c) => c.id)).toEqual(['framework', 'hal', 'hw'])
    const calls = lay.rows.filter((r) => r.kind === 'call')
    expect(calls[calls.length - 1].n).toBe(calls.length)
    expect(lay.loops.map((l) => l.inFlight)).toEqual([2, 1])
  })

  it('summary: end-to-end excludes the lead of steps issued units ahead; in-flight = ⌈e2e / period⌉', () => {
    const lay = layoutFlow(doc, doc.flows[0], 'layer')
    expect(lay.e2e).toBeCloseTo(185.5 - 133.3)
    expect(lay.lead).toBeCloseTo(133.3)
    expect(lay.inFlight).toBe(2)
    expect(lay.hw).toBeCloseTo(10 + 1.8 + 15.5 + 7.5)
  })

  it('cadence links: where one rate hands work to another', () => {
    expect(cadenceLinks(doc).sort((a, b) => a.to.localeCompare(b.to))).toEqual([
      { from: 'frame', to: 'od', n: 1, via: ['OD'] },
      { from: 'frame', to: 'vsync', n: 1, via: ['scanout'] },
    ])
  })
})

describe('trace-derived hand-off', () => {
  const ev = (id: string, layer: string, group: string, proc: string, thread: string, s: number, e: number, extra: Partial<TimelineEvent> = {}): TimelineEvent => ({
    task_id: id, logical_task_id: id.split('#')[0], layer, start_ms: s, end_ms: e, resource_name: `fullstack/${group}/${proc} · ${thread}`, ...extra })
  const tl = buildTimeline([
    ev('req#f0', 'hal', 'HAL', 'camera.provider', 'request', 0, 2, { frame_index: 0 }),
    ev('isp#f0', 'hw', 'HW', 'ISP', 'RT', 2, 12, { frame_index: 0, node_id: 'csis', predecessors: ['req#f0'], handoff: 'kick' }),
    ev('eis#f0', 'hal', 'HAL', 'camera.provider', 'VDISCore', 13, 20, { frame_index: 0, predecessors: ['isp#f0'], handoff: 'complete' }),
    ev('isp#f1', 'hw', 'HW', 'ISP', 'RT', 35.3, 45.3, { frame_index: 1 }),
    ev('abox#c0', 'hw', 'HW', 'ABOX', 'capture', 21, 21.8, { frame_index: null, cadence_period_ms: 20, predecessors: ['eis#f0'] }),
  ], { maxFrames: 8, groupOrder: FULLSTACK_GROUPS })

  it('turns the selected chain into one flow on process participants', () => {
    const d = deriveHandoff(tl, tl.slices.find((s) => s.id === 'eis#f0')!)
    expect(d.participants.map((p) => p.id)).toEqual(['hal.camera.provider', 'hw.ISP', 'hw.ABOX'])
    expect(d.participants[0].detail).toBe('request · VDISCore')
    const steps = d.flows[0].steps
    expect(steps.map((s) => s.slice)).toEqual(['req#f0', 'isp#f0', 'eis#f0', 'abox#c0'])
    expect(steps[1]).toMatchObject({ from: 'hal.camera.provider', to: 'hw.ISP', handoff: 'kick', node: 'csis' })
    expect(steps[3].cadence).toBe('p20.00')
    expect(d.cadences[0].period_ms).toBeCloseTo(33.3)
    expect(layoutFlow(d, d.flows[0], 'layer').columns.map((c) => c.id)).toEqual(['hal', 'hw'])
  })
})

describe('folding', () => {
  const isp: HandoffDoc = {
    format: 'sdb.handoff/1',
    participants: [{ id: 'k.is', layer: 'kernel', name: 'pablo-is' }, { id: 'hw.rt', layer: 'hw', name: 'ISP RT' }, { id: 'hw.vps', layer: 'hw', name: 'VPS' }],
    cadences: [{ id: 'frame', name: 'frame', kind: 'frame', period_ms: 33.3 }, { id: 'od', name: 'OD', kind: 'divided', of: 'frame', every: 5 }],
    flows: [{ id: 'f', name: 'f', cadence: 'frame', steps: [
      { from: 'k.is', to: 'hw.rt', call: 'CSIS', t_ms: 0, dur_ms: 10 },
      { from: 'hw.rt', to: 'hw.rt', call: 'PDP', t_ms: 0.1, dur_ms: 10 },
      { from: 'hw.rt', to: 'hw.rt', call: 'MLSC', t_ms: 0.2, dur_ms: 10 },
      { from: 'hw.rt', to: 'hw.vps', call: 'OD', cadence: 'od', t_ms: 10.5, dur_ms: 1.8 },
      { from: 'hw.vps', to: 'hw.vps', call: 'OD post', t_ms: 12.4, dur_ms: 0.2 },
    ] }],
  }

  it('a run of work inside one participant becomes one row; badged steps never fold', () => {
    const rows = layoutFlow(isp, isp.flows[0], 'participant').rows
    expect(rows.map((r) => r.step.call)).toEqual(['CSIS', 'OD', 'OD post'])
    expect(rows[0].kind === 'call' && rows[0].folded?.map((s) => s.call)).toEqual(['CSIS', 'PDP', 'MLSC'])
    expect(layoutFlow(isp, isp.flows[0], 'participant', false).rows).toHaveLength(5)
  })
})
