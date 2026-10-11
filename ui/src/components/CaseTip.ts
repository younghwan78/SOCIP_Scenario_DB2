// Hover popover for an exploration case row: what the key actually sets (SW condition, per-buffer compression
// mode + ratio, DVFS level per domain with MHz/mV), its power split and Δ vs baseline / IQ-keeping optimum.
import type { TipContent, TipRow } from './ChartTip'
import { IQ_LABEL, type ExpCase, type IqClass, type VariantResult } from '../lib/archExplore'
import { fmt } from '../lib/timingBudget'

const s = (v: number, d = 1) => `${v > 0 ? '+' : ''}${fmt(v, d)}`
const modeName = (m?: string) => (m ? (m.toUpperCase().endsWith('LOSSLESS') ? 'lossless' : m.toUpperCase().endsWith('LOSSY') ? 'lossy' : m) : '?')

export function caseIq(c: ExpCase): IqClass {
  return c.lossy && c.compression.length ? 'trade' : 'neutral'
}

export function caseTip(c: ExpCase, v: VariantResult): TipContent {
  const base = v.baseline
  const keep = v.tiers?.keep?.best
  const rows: (TipRow | { section: string })[] = [
    { k: 'SW 조건', v: `${c.statistic} ×${c.runtime_scale}${c.statistic !== base.statistic || c.runtime_scale !== base.runtime_scale ? ' (baseline과 다름)' : ''}` },
    { k: '판정', v: c.verdict, tone: c.verdict === 'fail' ? 'bad' : 'muted' },
    { section: 'Compression' },
  ]
  if (!c.compression.length) rows.push({ k: '—', v: '무압축', tone: 'muted' })
  for (const b of c.compression) {
    const mode = c.compression_modes?.[b]
    const row = v.buffers.find((x) => x.buffer === b)
    const m = row?.modes?.find((x) => x.mode === mode) ?? row
    rows.push({ k: b, v: `${modeName(mode ?? m?.mode)} · ratio ${m?.comp_ratio ?? '?'}${m?.ratio_source ? ` (${m.ratio_source})` : ''} · ${s(m?.delta_mw ?? 0)} mW · ${s(m?.delta_mbs ?? 0, 0)} MB/s`,
      tone: modeName(mode ?? m?.mode) === 'lossy' ? 'bad' : 'good' })
  }
  rows.push({ section: 'DVFS' })
  for (const d of v.domains) {
    const lv = c.dvfs[d.domain] ?? d.base_level
    const o = d.options.find((x) => x.level === lv)
    rows.push({ k: d.domain, v: `L${lv} · ${fmt(o?.speed_mhz ?? 0, 0)} MHz · ${fmt(o?.voltage_mv ?? 0, 1)} mV${o?.raise ? ` · 해석 level보다 ↑ ${s(o.delta_mw, 1)} mW (여유용)` : ' · 해석 level'}`,
      tone: o?.raise ? 'bad' : 'muted' })
  }
  rows.push({ section: 'Power' })
  rows.push({ k: 'CPU / CPU BW', v: `${fmt(c.cpu_mw, 1)} / ${fmt(c.bw_cpu_mw ?? 0, 1)} mW` })
  rows.push({ k: 'IP / IP BW', v: `${fmt(c.hw_mw, 1)} / ${fmt(c.bw_ip_mw ?? c.bw_mw, 1)} mW` })
  rows.push({ k: 'DRAM BW', v: `${fmt(c.bw_mbs / 1000, 2)} GB/s` })
  rows.push({ k: 'baseline 대비', v: `${s(c.total_mw - base.total_mw)} mW`, tone: c.total_mw < base.total_mw ? 'good' : 'bad' })
  if (keep) rows.push({ k: '화질 무손실 최적 대비', v: `${s(c.total_mw - keep.total_mw)} mW`, tone: c.total_mw <= keep.total_mw ? 'good' : 'bad' })
  const iq = caseIq(c)
  return {
    title: `${fmt(c.total_mw, 1)} mW · ${IQ_LABEL[iq]}`, color: iq === 'trade' ? '#9B1C1C' : '#2F6F68',
    rows,
    foot: 'power option(IP mode · L0 skip · bcrop)은 이 표에 없음 — Lever 분석 / Power option 카드 참고',
  }
}
