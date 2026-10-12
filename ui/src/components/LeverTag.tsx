import type { LeverPill } from '../lib/graph'
import type { MemoryLevers } from '../lib/api'
import type { LeverKey } from '../lib/memLever'

/** Solid pill for an active power lever (LLC / SBWC / vOTF) — same colours as the diagram. */
export function LeverTag({ k, text, title }: { k: LeverKey; text: string; title?: string }) {
  return <span className={`lv lv-${k}`} title={title}>{text}</span>
}

export function LeverTags({ pills, empty = '—' }: { pills: LeverPill[]; empty?: string }) {
  if (!pills.length) return <span className="faint">{empty}</span>
  return <span className="lv-row">{pills.map((p) => <LeverTag key={p.key} k={p.key} text={p.text} title={p.title} />)}</span>
}

/** Pills for a variant-matrix row (server-side lever summary). */
export function variantPills(ml?: MemoryLevers | null): LeverPill[] {
  if (!ml) return []
  const out: LeverPill[] = []
  if (ml.llc?.length) out.push({ key: 'llc', text: `LLC ${ml.llc.length}${ml.llc_weight_min ? ` ×${ml.llc_weight_min}` : ''}`, title: `LLC buffer: ${ml.llc.join(', ')}` })
  if (ml.compressed?.length) out.push({ key: 'sbwc', text: `압축 ${ml.compressed.length}`, title: `SBWC/AFBC 압축 buffer: ${ml.compressed.join(', ')}` })
  if (ml.votf?.length) out.push({ key: 'votf', text: `vOTF ${ml.votf.length}`, title: `vOTF: ${ml.votf.join(', ')}` })
  return out
}

const leverScore = (ml?: MemoryLevers | null) => (ml ? (ml.llc?.length ?? 0) * 100 + (ml.compressed?.length ?? 0) * 10 + (ml.votf?.length ?? 0) : null)
const leverKey = (ml?: MemoryLevers | null) => (ml ? JSON.stringify([
  ...[ml.llc, ml.compressed, ml.votf, ml.llc_owners].map((x) => [...(x ?? [])].sort()),
  ml.llc_mb ?? null, ml.llc_weight_min ?? null, ml.llc_unsized ?? 0, ml.compressed_dma ?? null,
]) : '')

/** Column spec shared by the variant tables (Explorer / Matrix). ``ref`` = row to diff against (yellow cell when the lever set differs). */
export function leverColumn<T>(get: (r: T) => MemoryLevers | null | undefined, ref?: (r: T) => MemoryLevers | null | undefined) {
  return {
    key: 'lever', label: 'Lever', width: 96, firstDir: -1 as const,
    headTitle: 'Memory power lever — LLC 상주 buffer 수 (×최소 llc_weight) · SBWC/AFBC 압축 buffer 수 · vOTF 연결 수',
    sort: (r: T) => leverScore(get(r)) || null,
    title: (r: T) => variantPills(get(r)).map((p) => p.title ?? p.text).join('\n'),
    cellClass: (r: T) => { const b = ref?.(r); return b !== undefined && leverKey(b) !== leverKey(get(r)) ? 'chg' : '' },
    render: (r: T) => (get(r) ? <LeverTags pills={variantPills(get(r))} empty="없음" /> : <span className="faint">…</span>),
  }
}
