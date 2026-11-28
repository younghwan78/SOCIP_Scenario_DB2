import { describe, expect, it } from 'vitest'
import { contractBadges, registrationPath } from './contract'
import { changeKind, type BoardRow } from './archExplore'
import type { ScenarioContract } from './api'

const audio: ScenarioContract = { rate: 'hz 50', sinks: [{ node: 'speaker', kind: 'audio' }, { node: 'bt_codec', kind: 'audio' }], kpis: ['latency', 'underrun'], targets: 1, jobs: [], subsystems: ['abox'] }
const capture: ScenarioContract = { rate: null, sinks: [], kpis: ['event_latency', 'peak_bw'], targets: 6, jobs: ['still_shot'], subsystems: [] }

describe('scenario contract (X-06, X-15)', () => {
  it('lists rate, sink kinds, KPI, job and subsystem badges', () => {
    expect(contractBadges(audio).map((b) => b.text)).toEqual(['rate: hz 50', 'sink: audio', 'KPI 2', 'subsystem ABOX'])
    expect(contractBadges(capture).map((b) => b.text)).toEqual(['KPI 2', 'job 1'])
    expect(contractBadges(null)).toEqual([])
  })
  it('says why a scenario has no registration', () => {
    expect(registrationPath(capture).kind).toBe('event_job')
    expect(registrationPath(audio).kind).toBe('not_judged')
    expect(registrationPath({ ...audio, sinks: [{ node: 'disp', kind: 'display' }, ...audio.sinks] }).kind).toBe('registrable')
    expect(registrationPath(undefined).kind).toBe('registrable')
  })
})

describe('re-registration change kind (X-09)', () => {
  const row = (previous: BoardRow['previous'], verdict = 'ok') => ({ previous, verdict })
  it('splits value change, same recompute and condition change', () => {
    expect(changeKind(row(null))).toBe('first')
    expect(changeKind(row({ id: 'p', total_mw: 600, delta_mw: 0, verdict: 'ok', condition_changed: false }))).toBe('same')
    expect(changeKind(row({ id: 'p', total_mw: 600, delta_mw: 0.04, verdict: 'ok', condition_changed: false }))).toBe('same')
    expect(changeKind(row({ id: 'p', total_mw: 600, delta_mw: -5.7, verdict: 'ok', condition_changed: false }))).toBe('value')
    expect(changeKind(row({ id: 'p', total_mw: 600, delta_mw: 0, verdict: 'clock_up', condition_changed: false }))).toBe('value')
    expect(changeKind(row({ id: 'p', total_mw: 600, delta_mw: 0, verdict: 'ok', condition_changed: true }))).toBe('condition')
    // older API without the new fields: by Δ only
    expect(changeKind(row({ id: 'p', total_mw: 600, delta_mw: 0 }))).toBe('same')
  })
})
