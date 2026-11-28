/** X-05: the verdict notes box mixed the judgement scope (why the timing verdict does not apply, which sinks are
 * not judged by frame interval) with the clock-up and pipeline-latency notes. The server writes them as plain
 * strings; the patterns below are the producers in sim/timing_budget.py (verdict notes) and the sink note. */
export type NoteKind = 'scope' | 'clock' | 'latency' | 'other'

export const NOTE_KIND_LABEL: Record<NoteKind, string> = {
  scope: '판정 범위', clock: 'clock 상향', latency: 'pipeline latency', other: '기타',
}

export function noteKind(note: string): NoteKind {
  if (/timing 판정을 적용하지 않음|frame interval로 판정하지 않는 sink|판정할 RT 단계/.test(note)) return 'scope'
  if (/buffering으로 latency/.test(note)) return 'latency'
  if (/MHz > rule|domain 공유/.test(note)) return 'clock'
  return 'other'
}

export function groupNotes(notes: string[] | undefined): { kind: NoteKind; notes: string[] }[] {
  const order: NoteKind[] = ['scope', 'clock', 'latency', 'other']
  const by = new Map<NoteKind, string[]>()
  for (const n of notes ?? []) { const k = noteKind(n); by.set(k, [...(by.get(k) ?? []), n]) }
  return order.filter((k) => by.has(k)).map((k) => ({ kind: k, notes: by.get(k)! }))
}

/** Sinks named by the "frame interval로 판정하지 않는 sink: speaker (audio), …" note: the declared sink names
 * replace the camera wording ("preview · video sink") in the scope explanation. */
export function unjudgedSinks(notes: string[] | undefined): string[] {
  const n = (notes ?? []).find((x) => x.includes('frame interval로 판정하지 않는 sink'))
  if (!n) return []
  const tail = n.split(':').slice(1).join(':')
  return tail.split(',').map((s) => s.trim()).filter(Boolean)
}

/** The scope sentence shown next to the badge, in the scenario's own sink words. */
export function scopeText(notes: string[] | undefined, fpsSource?: string | null): string | null {
  const scope = (notes ?? []).filter((n) => noteKind(n) === 'scope')
  if (!scope.length) return null
  const sinks = unjudgedSinks(notes)
  const head = scope.some((n) => n.includes('적용하지 않음'))
    ? 'frame 간격으로 판정할 RT 단계 · 출력이 없어 timing 판정을 적용하지 않습니다.'
    : '일부 출력은 frame 간격으로 판정하지 않습니다.'
  return [head, sinks.length ? `간격 판정 밖 sink: ${sinks.join(', ')}.` : null,
    fpsSource ? `판정 주기 출처: ${fpsSource}.` : null, 'KPI가 선언된 경우 그 판정은 KPI 칸에 따로 표시합니다.'].filter(Boolean).join(' ')
}
