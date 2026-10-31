// Processing flow (sdb.handoff/1): the in-house hand-off order as data → sequence-diagram layout.
// Design: docs/design/handoff-flow-ko.md. A full-stack trace without a hand-off document is turned into
// the same model (deriveHandoff) so one renderer serves both.
import type { HandoffCadence, HandoffDoc, HandoffFlow, HandoffStep } from './api'
import { chainOf, displayName, frameStarts, LAYER_COLORS, type Slice, type Timeline } from './timeline'

export const LAYERS = ['app', 'framework', 'hal', 'kernel', 'fw', 'hw'] as const
export const LAYER_LABEL: Record<string, string> = { app: 'App', framework: 'Framework', hal: 'HAL', kernel: 'Kernel', fw: 'FW', hw: 'HW' }
const layerIx = (l: string) => { const i = (LAYERS as readonly string[]).indexOf(l); return i < 0 ? LAYERS.length : i }
/** Layer colour shared by Full-stack timing groups (APP …) and Processing flow columns (app …). */
export const layerColor = (layer: string) => LAYER_COLORS[layer.toUpperCase()]?.strong

/** Effective rate of a cadence (divided = base period × every); null for event cadences. */
export function cadencePeriod(doc: HandoffDoc, id: string | undefined, seen = new Set<string>()): number | null {
  const c = doc.cadences.find((x) => x.id === id)
  if (!c || seen.has(c.id)) return null
  if (c.kind === 'divided') { const base = cadencePeriod(doc, c.of, new Set([...seen, c.id])); return base && c.every ? base * c.every : null }
  return c.period_ms ?? null
}
export const fmtHz = (period: number | null) => {
  if (!period) return '비주기'
  const hz = 1000 / period
  return `${hz >= 10 ? hz.toFixed(0) : hz >= 1 ? hz.toFixed(1).replace(/\.0$/, '') : hz.toFixed(2)} Hz`
}
/** A step's name in the same form as the timelines: its Pipeline node, else its common task name, else the call. */
export const stepName = (s: HandoffStep) => (s.node ? displayName(s.node) : s.task ? displayName(s.task) : s.call ?? '')
export const cadenceLabel = (doc: HandoffDoc, id: string | undefined) => {
  const c = doc.cadences.find((x) => x.id === id)
  return c ? `${c.name} · ${fmtHz(cadencePeriod(doc, c.id))}` : id ?? ''
}

export type ColumnMode = 'layer' | 'participant'
export interface Column { id: string; layer: string; title: string; sub: string }
export interface CallRow {
  kind: 'call'; n: number; step: HandoffStep; from: number | null; to: number; flow: number
  wait: number | null; badges: { text: string; tone: 'cadence' | 'every' | 'offset' }[]; offRate: boolean
  /** steps folded into this row: a run of work inside one participant (ISP CSIS → … → MLSC) */
  folded?: HandoffStep[]
}
export interface NoteRow { kind: 'note'; step: HandoffStep; from: number; to: number; flow: number }
export type Row = CallRow | NoteRow
/** A framed block of rows: par (branches), loop (one unit repeating at its cadence), sub (steps on another cadence). */
export interface Frame {
  kind: 'par' | 'loop' | 'sub'; start: number; end: number; label: string; tag?: string; note?: string
  cadence?: string; segments?: { label: string; start: number }[]
}
export interface FlowSummary { e2e: number | null; lead: number | null; period: number | null; inFlight: number | null; hw: number; sw: number }
export interface FlowLayout extends FlowSummary { columns: Column[]; rows: Row[]; frames: Frame[]; loops: (FlowSummary & { flow: HandoffFlow })[] }

/** How a cadence repeats, as shown on loop frames and the loop strip. */
export function loopKind(doc: HandoffDoc, id: string | undefined): string {
  const c = doc.cadences.find((x) => x.id === id)
  if (!c) return ''
  const base = doc.cadences.find((x) => x.id === c.of)?.name ?? c.of
  return { frame: 'frame loop', vsync: 'vsync loop', period: 'independent loop', chunk: 'slow chunk loop', divided: `every ${c.every}th ${base}`, event: 'event-driven' }[c.kind]
}

function summarize(doc: HandoffDoc, flow: HandoffFlow): FlowSummary {
  const parts = new Map(doc.participants.map((p) => [p.id, p]))
  const calls = flow.steps.filter((s) => s.note === undefined)
  const timed = calls.filter((s) => s.t_ms !== undefined)
  const main = timed.filter((s) => !s.frame_offset)
  const span = (xs: HandoffStep[]) => xs.length ? Math.max(...xs.map((s) => s.t_ms! + (s.dur_ms ?? 0))) - Math.min(...xs.map((s) => s.t_ms!)) : null
  const e2e = span(main.length ? main : timed)
  const lead = main.length && main.length < timed.length ? Math.min(...main.map((s) => s.t_ms!)) - Math.min(...timed.map((s) => s.t_ms!)) : null
  const layerOf = (pid?: string) => (pid ? parts.get(pid)?.layer : undefined)
  const period = cadencePeriod(doc, flow.cadence)
  return {
    e2e, lead, period, inFlight: e2e && period ? Math.ceil(e2e / period - 1e-9) : null,
    hw: calls.filter((s) => layerOf(s.to) === 'hw').reduce((a, s) => a + (s.dur_ms ?? 0), 0),
    sw: calls.filter((s) => layerOf(s.to) !== 'hw').reduce((a, s) => a + (s.dur_ms ?? 0), 0),
  }
}

/** Columns, numbered rows, frames (par / loop / sub-loop) and summaries of one or more flows on shared columns. */
export function layoutFlows(doc: HandoffDoc, flows: HandoffFlow[], mode: ColumnMode, fold = true): FlowLayout {
  const parts = new Map(doc.participants.map((p) => [p.id, p]))
  const used = new Set(flows.flatMap((f) => f.steps.flatMap((s) => [s.from, s.to, ...(s.over ?? [])])).filter((x): x is string => !!x))
  const usedParts = doc.participants.filter((p) => used.has(p.id)).sort((a, b) => layerIx(a.layer) - layerIx(b.layer))
  const columns: Column[] = mode === 'participant'
    ? usedParts.map((p) => ({ id: p.id, layer: p.layer, title: p.name, sub: p.detail ?? '' }))
    : [...new Set(usedParts.map((p) => p.layer))].map((l) => {
        const names = usedParts.filter((p) => p.layer === l).map((p) => p.name)
        return { id: l, layer: l, title: names.slice(0, 2).join(' · '), sub: names.length > 2 ? `+ ${names.slice(2).join(' · ')}` : '' }
      })
  const colOf = (pid: string | undefined) => {
    if (!pid) return null
    const key = mode === 'participant' ? pid : parts.get(pid)?.layer
    const i = columns.findIndex((c) => c.id === key)
    return i < 0 ? null : i
  }
  let n = 0
  const rows: Row[] = []
  const frames: Frame[] = []
  flows.forEach((flow, fi) => {
    const first = rows.length
    const flowPeriod = cadencePeriod(doc, flow.cadence)
    const calls = flow.steps.filter((s) => s.note === undefined)
    // wait Δ: since the latest earlier call that ended on this step's caller
    const byTime = [...calls].sort((a, b) => (a.t_ms ?? 0) - (b.t_ms ?? 0))
    const waits = new Map<HandoffStep, number | null>()
    byTime.forEach((s, k) => {
      if (!s.from || s.t_ms === undefined) { waits.set(s, null); return }
      const prev = byTime.slice(0, k).reverse().find((p) => p.to === s.from && p.t_ms !== undefined)
      waits.set(s, prev ? Math.max(0, s.t_ms - ((prev.t_ms ?? 0) + (prev.dur_ms ?? 0))) : null)
    })
    for (const s of flow.steps) {
      if (s.note !== undefined) {
        const cs = (s.over ?? []).map(colOf).filter((c): c is number => c !== null)
        rows.push({ kind: 'note', step: s, from: Math.min(...cs), to: Math.max(...cs), flow: fi })
        continue
      }
      const badges: CallRow['badges'] = []
      const offRate = !!s.cadence && s.cadence !== flow.cadence
      if (offRate) badges.push({ text: `↻ ${cadenceLabel(doc, s.cadence)}`, tone: 'cadence' })
      else if (s.every) badges.push({ text: `÷${s.every} · ${fmtHz(flowPeriod ? flowPeriod * s.every : null)}`, tone: 'every' })
      if (s.frame_offset) badges.push({ text: `n${s.frame_offset > 0 ? '+' : '−'}${Math.abs(s.frame_offset)} 단위 앞`, tone: 'offset' })
      // fold a run of plain steps inside one participant into the row that started it
      const prev = rows[rows.length - 1]
      if (fold && prev?.kind === 'call' && prev.flow === fi && s.from === s.to && s.to === prev.step.to && !badges.length && !prev.badges.length && s.branch === prev.step.branch) {
        prev.folded = [...(prev.folded ?? [prev.step]), s]
        continue
      }
      rows.push({ kind: 'call', n: ++n, step: s, from: colOf(s.from), to: colOf(s.to)!, wait: waits.get(s) ?? null, badges, offRate, flow: fi })
    }
    const last = rows.length - 1
    if (flows.length > 1 && last >= first) {
      const sm = summarize(doc, flow)
      frames.push({ kind: 'loop', start: first, end: last, label: `${flow.name} · ${fmtHz(sm.period)}`, tag: loopKind(doc, flow.cadence), cadence: flow.cadence,
        note: sm.e2e !== null ? `e2e ${sm.e2e.toFixed(1)} ms${sm.inFlight ? ` · ${sm.inFlight} in flight` : ''}` : undefined })
    }
    // a note takes the branch / cadence of the call it annotates
    const attr = (i: number, key: 'branch' | 'cadence'): string | undefined => {
      const r = rows[i]
      if (r.kind === 'note') return i + 1 <= last ? attr(i + 1, key) : undefined
      return key === 'branch' ? r.step.branch : r.offRate ? r.step.cadence : undefined
    }
    // consecutive rows of one or more branches form a par block
    let par: Frame | null = null
    for (let i = first; i <= last; i++) {
      const b = attr(i, 'branch')
      if (!b) { par = null; continue }
      if (par && par.end === i - 1) {
        par.end = i
        if (par.segments![par.segments!.length - 1].label !== b) par.segments!.push({ label: b, start: i })
      } else frames.push(par = { kind: 'par', start: i, end: i, label: 'par', segments: [{ label: b, start: i }] })
    }
    // consecutive rows on another cadence form a sub-loop (vsync scanout inside a camera frame, AAC inside an ABOX period)
    let sub: Frame | null = null
    for (let i = first; i <= last; i++) {
      const c = attr(i, 'cadence')
      if (!c) { sub = null; continue }
      if (sub && sub.end === i - 1 && sub.cadence === c && rows[i].step.branch === rows[sub.start].step.branch) sub.end = i
      else frames.push(sub = { kind: 'sub', start: i, end: i, label: cadenceLabel(doc, c), tag: loopKind(doc, c), cadence: c })
    }
  })
  const single = flows.length === 1 ? summarize(doc, flows[0]) : { e2e: null, lead: null, period: null, inFlight: null, hw: 0, sw: 0 }
  return { columns, rows, frames, ...single, loops: flows.map((flow) => ({ flow, ...summarize(doc, flow) })) }
}

/** One flow on its own columns. */
export const layoutFlow = (doc: HandoffDoc, flow: HandoffFlow, mode: ColumnMode, fold = true) => layoutFlows(doc, [flow], mode, fold)

/** Where one cadence hands work to another (consecutive calls whose rate changes), counted over all flows. */
export function cadenceLinks(doc: HandoffDoc): { from: string; to: string; n: number; via: string[] }[] {
  const m = new Map<string, { n: number; via: Set<string> }>()
  for (const f of doc.flows) {
    const calls = f.steps.filter((s) => s.note === undefined).sort((a, b) => (a.t_ms ?? 0) - (b.t_ms ?? 0))
    const cadOf = (s: HandoffStep) => s.cadence ?? f.cadence
    // the caller of each step: the latest earlier call that ended on its `from`
    calls.forEach((s, i) => {
      const prev = calls.slice(0, i).reverse().find((p) => p.to === s.from)
      if (prev && cadOf(prev) !== cadOf(s)) {
        const k = `${cadOf(prev)}>${cadOf(s)}`
        const e = m.get(k) ?? { n: 0, via: new Set<string>() }
        e.n++
        if (stepName(s)) e.via.add(stepName(s))
        m.set(k, e)
      }
    })
  }
  return [...m.entries()].map(([k, e]) => { const [from, to] = k.split('>'); return { from, to, n: e.n, via: [...e.via] } })
}

/** A full-stack trace without a hand-off document: the selected slice's chain as a one-flow document. */
export function deriveHandoff(tl: Timeline, seed: Slice): HandoffDoc {
  const set = chainOf(tl, seed.id)
  const list = tl.slices.filter((s) => set.has(s.id)).sort((a, b) => a.start - b.start || a.end - b.end)
  const context = new Map(tl.groups.flatMap((g) => g.tracks).map((t) => [t.id, t.context ?? t.name]))
  const partOf = (s: Slice) => {
    const [proc, ...thread] = (context.get(s.track) ?? s.track).split(' · ')
    const layer = (s.layer ?? s.group).toLowerCase()
    return { id: `${layer}.${proc}`, layer, name: proc, thread: thread.join(' · ') }
  }
  const participants = new Map<string, { id: string; layer: string; name: string; detail: string }>()
  for (const s of list) {
    const p = partOf(s)
    const cur = participants.get(p.id)
    if (!cur) participants.set(p.id, { id: p.id, layer: p.layer, name: p.name, detail: p.thread })
    else if (p.thread && !cur.detail.split(' · ').includes(p.thread)) cur.detail = cur.detail ? `${cur.detail} · ${p.thread}` : p.thread
  }
  const starts = frameStarts(tl).map((f) => f.t)
  const gaps = starts.slice(1).map((t, i) => t - starts[i]).sort((a, b) => a - b)
  const framePeriod = gaps.length ? gaps[Math.floor(gaps.length / 2)] : undefined
  const cadences: HandoffCadence[] = [{ id: 'frame', name: 'frame', kind: 'frame', period_ms: framePeriod ?? 33.333 }]
  const cadOf = (s: Slice) => {
    if (!s.period) return 'frame'
    const id = `p${s.period.toFixed(2)}`
    if (!cadences.some((c) => c.id === id)) cadences.push({ id, name: `자기 주기 ${s.period.toFixed(1)} ms`, kind: 'period', period_ms: s.period })
    return id
  }
  const flowCad = cadOf(seed)
  const byId = new Map(list.map((s) => [s.id, s]))
  const t0 = list[0]?.start ?? 0
  const steps: HandoffStep[] = list.map((s) => {
    const ins = tl.flows.filter((f) => f.to === s.id && byId.has(f.from)).sort((a, b) => byId.get(b.from)!.end - byId.get(a.from)!.end)
    const step: HandoffStep = { to: partOf(s).id, task: s.task, slice: s.id, t_ms: s.start - t0, dur_ms: s.end - s.start }
    if (ins[0]) { step.from = partOf(byId.get(ins[0].from)!).id; if (ins[0].type && ins[0].type !== 'data') step.handoff = ins[0].type }
    if (s.nodeId) step.node = s.nodeId
    const c = cadOf(s)
    if (c !== flowCad) step.cadence = c
    return step
  })
  return { format: 'sdb.handoff/1', generator: 'trace chain', participants: [...participants.values()], cadences,
    flows: [{ id: 'chain', name: `${seed.label} chain`, cadence: flowCad, summary: '선택한 slice의 앞뒤 hand-off (trace에서 유도)', steps }] }
}
