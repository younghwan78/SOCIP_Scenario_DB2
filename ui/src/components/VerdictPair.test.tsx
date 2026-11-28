// @vitest-environment jsdom
import { act, type ReactElement } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it } from 'vitest'
import { VerdictPair, kpiPairText } from './VerdictPair'
import { groupNotes, noteKind, scopeText, unjudgedSinks } from '../lib/verdictNotes'
import { KpiTable, splitKpiRows } from './KpiTable'
import { SubsystemCard } from './SubsystemCard'
import type { KpiResult, Subsystem, Verdict } from '../lib/timingBudget'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
let root: HTMLElement = document.body
function render(node: ReactElement) { const el = document.createElement('div'); act(() => createRoot(el).render(node)); root = el; return { container: el } }
const byId = (id: string) => { const e = root.querySelector(`[data-testid="${id}"]`); if (!e) throw new Error(`no ${id}`); return e }
const byLabel = (l: string) => root.querySelector(`[aria-label="${l}"]`)
const byText = (s: string) => [...root.querySelectorAll('*')].find((e) => e.children.length === 0 && e.textContent === s) ?? null
const AUDIO_NOTES = ['판정할 RT 단계와 출력(preview · video sink)이 없어 timing 판정을 적용하지 않음', 'frame interval로 판정하지 않는 sink: speaker (audio), bt (audio)']
const kpi = (o: Partial<KpiResult>): KpiResult => ({ id: null, kpi: 'event_latency', metric: null, job: 'still_shot', milestone: 'thumb', status: 'pass', value: 167, target: 300, bound: 'max', unit: 'ms', value_source: 'assumed', basis: null, sources: [], ...o })

describe('verdict notes (X-05)', () => {
  it('classifies scope, clock and latency notes', () => {
    expect(noteKind(AUDIO_NOTES[0])).toBe('scope')
    expect(noteKind(AUDIO_NOTES[1])).toBe('scope')
    expect(noteKind('NRT CAM: 필요 410.0 MHz > rule 400 → 533 MHz (L3→L4)')).toBe('clock')
    expect(noteKind('NRT CAM: domain 공유 (MCSC)로 533 MHz (자체 필요 120.0)')).toBe('clock')
    expect(noteKind('NRT: SW+HW 40.1 ms > period 33.3 ms → buffering으로 latency +1 frame (fps는 출력 간격으로 판정)')).toBe('latency')
    expect(noteKind('something else')).toBe('other')
    expect(groupNotes([...AUDIO_NOTES, 'x']).map((g) => g.kind)).toEqual(['scope', 'other'])
  })
  it('names the declared sinks instead of the camera wording', () => {
    expect(unjudgedSinks(AUDIO_NOTES)).toEqual(['speaker (audio)', 'bt (audio)'])
    const t = scopeText(AUDIO_NOTES, 'target_fps')!
    expect(t).toContain('speaker (audio)')
    expect(t).toContain('target_fps')
    expect(t).not.toContain('preview · video')
    expect(scopeText(['NRT CAM: 필요 1 MHz > rule 0 → 1 MHz'])).toBeNull()
  })
})

describe('VerdictPair (X-04)', () => {
  it('shows two cells for audio: timing not applicable, KPI pass 2', () => {
    const v: Verdict = { status: 'not_applicable', reasons: [], notes: AUDIO_NOTES, nrt_clock_factor: 1, kpis: { status: 'pass', pass: 2 } }
    render(<VerdictPair verdict={v} />)
    expect(byId('verdict-timing').textContent).toBe('판정 미지원')
    expect(byId('verdict-kpi-pass').textContent).toBe('통과 2')
    expect(byLabel('판정 범위')).toBeTruthy()
  })
  it('names failing KPIs and omits the KPI cell when none is declared', () => {
    const rows = [kpi({ kpi: 'heap', milestone: null, status: 'fail' }), kpi({})]
    expect(kpiPairText({ status: 'fail', fail: 1, pass: 1 }, rows)?.text).toBe('KPI 미달 1 (heap) · 통과 1')
    // capture: a reference-only KPI does not hide the passes nor colour the cell
    const cap = kpiPairText({ status: 'no_target', no_target: 2, pass: 4 })!
    expect(cap.text).toBe('KPI 통과 4 · 목표 없음 2')
    expect(cap.cls).toBe('v-ok')
    const { container } = render(<VerdictPair verdict={{ status: 'ok', reasons: [], nrt_clock_factor: 1 }} />)
    expect(container.querySelector('[data-testid^="verdict-kpi"]')).toBeNull()
    expect(byLabel('판정 범위')).toBeNull()
  })
})

describe('KpiTable (X-12)', () => {
  it('splits target-less KPIs into reference values and the evidence into badges', () => {
    const rows = [kpi({ sources: ['assumed'], basis: 'about 65 % of an assumed LPDDR5X' }), kpi({ kpi: 'event_energy', target: null, status: 'no_target', value: 9.1, unit: 'mJ', milestone: null })]
    expect(splitKpiRows(rows).reference).toHaveLength(1)
    render(<KpiTable rows={rows} />)
    expect(byText('가정 목표')).toBeTruthy()
    expect(byId('kpi-reference').textContent).toContain('목표가 없는 KPI')
    expect(root.querySelector('details > summary')).toBeTruthy()
  })
})

describe('SubsystemCard (X-03)', () => {
  it('shows units, domain, slack, route and residency of ABOX', () => {
    const s: Subsystem = {
      model: 'mcps-v1', mw: 3.289, feasible: true,
      domains: { AUD: { freq_mhz: 200, levels_mhz: [200, 332], max_util: 0.215, pinned: true } },
      units: [{ id: 'hifi5', kind: 'dsp', value_source: 'assumed', load_mcps: 43, util: 0.215, target_util: 0.85, mw: 1.655 }],
      deadline_slack: [{ stream: 'pb_out', period_ms: 5, unit: 'hifi5', slack_ms: 3.925 }],
      wake: { per_s: 0.5, sources: [{ kind: 'refill', per_s: 0.5, every_ms: 2000, mb: 0.08 }] },
      route: { id: 'pb_speaker', kind: 'playback', stages: ['rdma', 'decode'], latency_ms: 52.875, latency_target_ms: 60, latency_ok: true, buffering_ms: 50, processing_ms: 2.875 },
    }
    render(<SubsystemCard subsystems={{ abox: s }} residency={{ model: 'wake-residency-v1', wakeups_per_s: 0.5, sources: [{ node: 'abox', kind: 'refill', per_s: 0.5, every_ms: 2000, mb: 0.08 }], screen_on: false, status: 'no_coefficients', note: 'config.residency 계수 없음' }} />)
    expect(byId('ss-unit-hifi5').textContent).toContain('43.0')
    expect(byId('ss-domain-AUD').textContent).toContain('200 MHz')
    expect(byId('ss-domain-AUD').textContent).toContain('level 1 / 2')
    expect(byId('ss-slack-pb_out').textContent).toContain('3.92 / 5.0 ms')
    expect(byId('ss-route-pb_speaker').textContent).toContain('52.9 ms')
    expect(byId('residency').textContent).toContain('config.residency 계수 없음')
  })
})
