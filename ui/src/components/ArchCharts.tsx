import { useWidth } from './Charts'
import { useTip } from './ChartTip'
import { fmt, niceMax } from '../lib/timingBudget'
import { CAT_COLOR, PCOL, powerParts, waterfall, type Attribution, type BufferRow, type DomainRow, type IpModeRow, type Power, type Quant } from '../lib/archExplore'

// ---------------------------------------------------------------- range boxes (one row per scenario, no overlap)
export interface RangeRow { id: string; label: string; dist: Quant | null | undefined; marker?: number | null; base?: number | null; ok: boolean }
/** One row per scenario (no overlap): distribution box + recommended ◆ + baseline ○ on one value axis. */
export function RangeBoxes({ rows, unit, onPick, selected, color = PCOL.total }: {
  rows: RangeRow[]; unit: string; onPick?: (id: string) => void; selected?: string; color?: string
}) {
  const [ref, w] = useWidth<HTMLDivElement>(700)
  const labelW = 170, valW = 118, rh = 20
  const plotW = Math.max(160, w - labelW - valW - 12)
  const hi = niceMax(Math.max(1, ...rows.flatMap((r) => [r.dist?.max ?? 0, r.marker ?? 0, r.base ?? 0])))
  const k = plotW / hi
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * hi)
  return (
    <div ref={ref} style={{ width: '100%' }}>
      <svg width={labelW + plotW + valW} height={rows.length * rh + 22} role="img" aria-label={`range ${unit}`}>
        {ticks.map((t) => <g key={t}><line x1={labelW + t * k} x2={labelW + t * k} y1={0} y2={rows.length * rh + 4} stroke="#EFEAE1" />
          <text x={labelW + t * k} y={rows.length * rh + 16} fontSize={10} fill="#8A8274" textAnchor="middle">{fmt(t, 0)}</text></g>)}
        {rows.map((r, i) => {
          const y = i * rh + 2, d = r.dist, col = r.ok ? color : '#9B1C1C'
          return (
            <g key={r.id} transform={`translate(0,${y})`} style={{ cursor: onPick ? 'pointer' : undefined }} onClick={() => onPick?.(r.id)}>
              <rect x={0} y={0} width={labelW + plotW + valW} height={rh - 2} fill={selected === r.id ? '#F3EFE8' : 'transparent'} />
              <title>{`${r.label}${d ? ` · min ${fmt(d.min, 0)} · p25 ${fmt(d.p25, 0)} · med ${fmt(d.median, 0)} · p75 ${fmt(d.p75, 0)} · max ${fmt(d.max, 0)} ${unit}` : ''}${r.marker != null ? ` · 추천 ${fmt(r.marker, 1)}` : ''}${r.base != null ? ` · baseline ${fmt(r.base, 1)}` : ''}`}</title>
              <text x={labelW - 6} y={13} fontSize={11} textAnchor="end" fill="#3B3F4A" className="mono">{r.label.length > 26 ? `${r.label.slice(0, 25)}…` : r.label}</text>
              {d && <>
                <line x1={labelW + d.min * k} x2={labelW + d.max * k} y1={9} y2={9} stroke={col} />
                <rect x={labelW + d.p25 * k} y={3} width={Math.max(1.5, (d.p75 - d.p25) * k)} height={12} fill={col} fillOpacity={0.18} stroke={col} />
                <line x1={labelW + d.median * k} x2={labelW + d.median * k} y1={3} y2={15} stroke={col} strokeWidth={2} />
              </>}
              {r.base != null && <circle cx={labelW + r.base * k} cy={9} r={4} fill="#FFFFFF" stroke="#3B3F4A" />}
              {r.marker != null && <path d={`M${labelW + r.marker * k},2 l5,7 l-5,7 l-5,-7z`} fill="#CC3311" stroke="#FFFFFF" strokeWidth={0.8} />}
              <text x={labelW + plotW + 8} y={13} fontSize={11} fill="#6B6458" className="mono">{d ? `${fmt(d.min, 0)}–${fmt(d.max, 0)}` : '—'}</text>
            </g>
          )
        })}
      </svg>
      <div className="legend-row" style={{ paddingLeft: labelW }}>
        <span className="legend-item"><svg width={24} height={12}><line x1={0} x2={24} y1={6} y2={6} stroke={color} /><rect x={6} y={1} width={12} height={10} fill={color} fillOpacity={0.18} stroke={color} /></svg>조합 × SW 통계 분포 (min·p25·median·p75·max)</span>
        <span className="legend-item"><svg width={12} height={14}><path d="M6,0 l5,7 l-5,7 l-5,-7z" fill="#CC3311" /></svg>최저 power 추천</span>
        <span className="legend-item"><svg width={12} height={12}><circle cx={6} cy={6} r={4} fill="#fff" stroke="#3B3F4A" /></svg>baseline (변경 없음)</span>
        <span className="legend-item"><span style={{ width: 10, height: 10, background: '#9B1C1C' }} />spec 미달</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- CPU / CPU BW / IP / IP BW split
export function SplitBar({ p, width = 90, height = 10, max }: { p: Power; width?: number; height?: number; max?: number }) {
  const t = Math.max(max ?? p.total_mw, 1e-9)
  let x = 0
  const parts = powerParts(p)
  return (
    <svg width={width} height={height} aria-label="CPU/IP/BW"><title>{parts.map((q) => `${q.label} ${fmt(q.mw, 1)}`).join(' · ') + ' mW'}</title>
      <rect width={width} height={height} fill="#F3EFE8" />
      {parts.map((q) => { const w = (q.mw / t) * width; const el = <rect key={q.key} x={x} width={Math.max(0, w)} height={height} fill={PCOL[q.key]} />; x += w; return el })}
    </svg>
  )
}

export function SplitLegend() {
  return <div className="legend-row">{powerParts({ total_mw: 0, cpu_mw: 0, hw_mw: 0, bw_mw: 0 }).map((q) =>
    <span key={q.key} className="legend-item"><span style={{ width: 10, height: 10, background: PCOL[q.key] }} />{q.label}</span>)}</div>
}

/** Absolute stacked bars of the recommended / registered case (separate from the range boxes). */
export function CompositionBars({ rows, onPick, selected }: { rows: { id: string; label: string; p: Power | null | undefined }[]; onPick?: (id: string) => void; selected?: string }) {
  const [ref, w] = useWidth<HTMLDivElement>(700)
  const labelW = 170, valW = 250, rh = 20
  const plotW = Math.max(160, w - labelW - valW - 12)
  const hi = niceMax(Math.max(1, ...rows.map((r) => r.p?.total_mw ?? 0)))
  const k = plotW / hi
  return (
    <div ref={ref} style={{ width: '100%' }}>
      <SplitLegend />
      <svg width={labelW + plotW + valW} height={rows.length * rh + 22} role="img" aria-label="power composition">
        {[0, 0.25, 0.5, 0.75, 1].map((t) => <g key={t}><line x1={labelW + t * hi * k} x2={labelW + t * hi * k} y1={0} y2={rows.length * rh + 4} stroke="#EFEAE1" />
          <text x={labelW + t * hi * k} y={rows.length * rh + 16} fontSize={10} fill="#8A8274" textAnchor="middle">{fmt(t * hi, 0)}</text></g>)}
        {rows.map((r, i) => {
          const p = r.p
          let x = labelW
          const parts = p ? powerParts(p) : []
          return (
            <g key={r.id} transform={`translate(0,${i * rh + 2})`} style={{ cursor: onPick ? 'pointer' : undefined }} onClick={() => onPick?.(r.id)}>
              <rect x={0} y={0} width={labelW + plotW + valW} height={rh - 2} fill={selected === r.id ? '#F3EFE8' : 'transparent'} />
              <title>{p ? `${r.label} · ${parts.map((q) => `${q.label} ${fmt(q.mw, 1)}`).join(' · ')} · total ${fmt(p.total_mw, 1)} mW` : r.label}</title>
              <text x={labelW - 6} y={13} fontSize={11} textAnchor="end" fill="#3B3F4A" className="mono">{r.label.length > 26 ? `${r.label.slice(0, 25)}…` : r.label}</text>
              {parts.map((q) => { const wq = Math.max(0, q.mw * k); const el = <rect key={q.key} x={x} y={3} width={wq} height={12} fill={PCOL[q.key]} />; x += wq; return el })}
              {p && <text x={labelW + plotW + 8} y={13} fontSize={11} fill="#3B3F4A" className="mono">
                {fmt(p.total_mw, 0)} mW <tspan fill="#8A8274">· {parts.map((q) => { const v = (100 * q.mw) / Math.max(p.total_mw, 1e-9); return fmt(v, v > 0 && v < 1 ? 1 : 0) }).join('/')} %</tspan></text>}
            </g>
          )
        })}
      </svg>
      <div className="faint" style={{ fontSize: 11 }}>% = CPU / CPU BW / IP / IP BW 비중</div>
    </div>
  )
}

// ---------------------------------------------------------------- range cause per axis
const AXIS_LABEL: Record<string, string> = { sw_statistic: 'SW 통계 (mean↔max)', sw_growth: '차기 SW 증가', compression: 'Compression', dvfs_headroom: 'DVFS headroom' }
export function AxisSpread({ spread }: { spread: Record<string, { min: number; max: number; range: number }> }) {
  const [ref, w] = useWidth<HTMLDivElement>(420)
  const rows = Object.entries(spread)
  const labelW = 130, valW = 70
  const plotW = Math.max(120, w - labelW - valW)
  const hi = niceMax(Math.max(1, ...rows.map(([, v]) => v.range)))
  return (
    <div ref={ref}>
      <svg width={labelW + plotW + valW} height={rows.length * 24} role="img" aria-label="axis spread">
        {rows.map(([k, v], i) => (
          <g key={k} transform={`translate(0,${i * 24})`}>
            <text x={labelW - 6} y={15} fontSize={12} textAnchor="end" fill="#3B3F4A">{AXIS_LABEL[k] ?? k}</text>
            <rect x={labelW} y={5} width={plotW} height={12} fill="#F7F4EF" />
            <rect x={labelW} y={5} width={(v.range / hi) * plotW} height={12} fill="#4C5E8C" />
            <text x={labelW + plotW + 6} y={15} fontSize={11} className="mono" fill="#3B3F4A">{fmt(v.range, 1)} mW</text>
          </g>
        ))}
      </svg>
      <div className="faint" style={{ fontSize: 11 }}>한 축만 움직일 때 total power 폭 (나머지는 목적 통계·baseline)</div>
    </div>
  )
}

// ---------------------------------------------------------------- compression savings
/** Buffer state for the compression axis: applied (recommended) / explored / not explored, and why. */
export function bufferState(b: BufferRow, selected: string[]): { key: 'on' | 'explored' | 'cap' | 'unsupported' | 'none'; label: string; color: string } {
  if (selected.includes(b.buffer)) return { key: 'on', label: '추천 조합 적용', color: '#EA8A4E' }
  if (b.explored) return { key: 'explored', label: '탐색 (미적용)', color: '#F2C9AD' }
  const r = b.skip_reason ?? ''
  if (/max_buffers/.test(r)) return { key: 'cap', label: '상한 제외', color: '#E7DFD2' }
  if (/not declared|port without|lists no compression/.test(r)) return { key: 'unsupported', label: 'DMA 미지원', color: '#D9D4CC' }
  return { key: 'none', label: '절감 없음', color: '#EDE7DD' }
}
function reasonText(b: BufferRow): string {
  const r = b.skip_reason ?? ''
  if (/not declared: (.*)/.test(r)) return `지원 미선언 IP: ${r.replace(/.*not declared: /, '')}`
  if (/DMA port without/.test(r)) { const ps = r.replace(/.*: /, '').split(', '); return `${r.match(/without (\S+):/)?.[1] ?? ''} 미지원 port: ${ps.length > 2 ? `${ps.slice(0, 2).join(', ')} 외 ${ps.length - 2}` : ps.join(', ')}` }
  if (/lists no compression/.test(r)) return 'endpoint IP가 압축 미지원'
  if (/max_buffers/.test(r)) return '절감 상위 N개 밖 (buffer 상한)'
  if (/already compressed/.test(r)) return '이미 압축 사용 중'
  return r
}

export function BufferSavings({ buffers, selected }: { buffers: BufferRow[]; selected: string[] }) {
  const [ref, w] = useWidth<HTMLDivElement>(420)
  const tip = useTip()
  const rows = buffers.filter((b) => (b.delta_mbs ?? 0) < -0.5 || /not declared|port without|lists no compression/.test(b.skip_reason ?? ''))
    .sort((a, b) => Number(!!b.explored || selected.includes(b.buffer)) - Number(!!a.explored || selected.includes(a.buffer)) || (a.delta_mbs ?? 0) - (b.delta_mbs ?? 0))
  const labelW = 150, valW = 150
  const plotW = Math.max(100, w - labelW - valW)
  const hi = niceMax(Math.max(1, ...rows.map((b) => -(b.delta_mbs ?? 0))))
  if (!rows.length) return <div className="empty">압축으로 줄일 DMA traffic 없음</div>
  const nUnsup = rows.filter((b) => bufferState(b, selected).key === 'unsupported').length
  return (
    <div ref={ref}>
      <div className="faint" style={{ fontSize: 11.5, marginBottom: 4 }}>압축 지원이 IP catalog에 선언된 DMA만 탐색합니다 (port별 supported_compressions 포함){nUnsup ? ` · 미지원 ${nUnsup}개는 회색 — 단독 적용 시 잠재 절감만 표시` : ''}</div>
      <svg width={labelW + plotW + valW} height={rows.length * 20} role="img" aria-label="compression savings">
        {rows.map((b, i) => {
          const st = bufferState(b, selected)
          const bw = (-(b.delta_mbs ?? 0) / hi) * plotW
          const off = st.key === 'unsupported' || st.key === 'cap' || st.key === 'none'
          return (
            <g key={b.buffer} transform={`translate(0,${i * 20})`}
              {...tip({ title: b.buffer, color: st.color, head: { label: st.label, value: `${fmt(b.delta_mbs, 0)} MB/s`, tone: off ? 'muted' : 'good' },
                rows: [{ k: 'Δ power', v: `${fmt(b.delta_mw, 1)} mW` }, { k: 'mode · ratio', v: `${b.mode ?? '—'} ×${b.comp_ratio ?? '—'} (${b.ratio_source ?? '—'})` },
                  { k: 'endpoint IP', v: b.nodes.join(', ') }, ...(b.ports?.length ? [{ k: 'DMA port', v: b.ports.length > 3 ? `${b.ports.slice(0, 3).join(', ')} 외 ${b.ports.length - 3}` : b.ports.join(', ') }] : []),
                  ...(b.skip_reason ? [{ k: '제외 사유', v: reasonText(b), tone: 'bad' as const }] : [])] })}>
              <rect x={0} y={0} width={labelW + plotW + valW} height={20} fill="transparent" />
              <text x={labelW - 6} y={13} fontSize={11} textAnchor="end" fill={off ? '#A39C90' : '#3B3F4A'} className="mono">{b.buffer}</text>
              <rect x={labelW} y={3} width={bw} height={12} fill={st.color} stroke={st.key === 'unsupported' ? '#B8B1A6' : undefined} strokeDasharray={st.key === 'unsupported' ? '3 2' : undefined} />
              <text x={labelW + plotW + 6} y={13} fontSize={11} className="mono" fill={off ? '#A39C90' : '#3B3F4A'}>{st.key === 'unsupported' ? 'DMA 미지원' : `${fmt(b.delta_mbs, 0)} MB/s · ${fmt(b.delta_mw, 1)}`}</text>
            </g>
          )
        })}
      </svg>
      <div className="legend-row">
        {[['#EA8A4E', '추천 조합에 적용'], ['#F2C9AD', '탐색 (미적용)'], ['#E7DFD2', '상한 제외 (max_buffers)'], ['#D9D4CC', 'DMA 미지원 (탐색 안 함)']].map(([c, l]) =>
          <span key={l} className="legend-item"><span style={{ width: 10, height: 10, background: c }} />{l}</span>)}
      </div>
    </div>
  )
}

/** Per-IP sim mode table: current mode / unit power, declared alternatives, explored saving. */
export function IpModes({ rows, results }: { rows: IpModeRow[]; results?: { items: string[]; delta_mw: number | null; spec_ok: boolean }[] }) {
  if (!rows.length) return <div className="empty">IP mode 정보 없음 (engine rev 6 이전 run)</div>
  const single = (node: string, mode: string) => results?.find((r) => r.items.length === 1 && r.items[0] === `mode:${node}=${mode}`)
  return (
    <div className="table-x">
      <table className="tb-mini-table" style={{ width: '100%' }} aria-label="IP mode">
        <thead><tr><th>IP</th><th>DVFS</th><th>현재 mode</th><th title="mW per MP (처리 화소)">unit power</th><th>ppc</th><th>IP power</th><th>대안 mode (unit power · 탐색 결과)</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.node}>
            <td><b>{r.node.toUpperCase()}</b> <span className="faint mono" style={{ fontSize: 11 }}>{r.hw_name !== r.node.toUpperCase() ? r.hw_name : ''}</span></td>
            <td className="mono faint">{r.dvfs_group ?? '—'}</td>
            <td><span className="badge">{r.mode}</span>{!r.declared && <span className="faint" style={{ fontSize: 11 }}> (mode 미선언)</span>}</td>
            <td className="mono">{r.unit_power_mw_mp === null ? '—' : `${fmt(r.unit_power_mw_mp, 3)}`}</td>
            <td className="mono">{fmt(r.ppc, 1)}</td>
            <td className="mono">{r.power_mw === null ? '—' : `${fmt(r.power_mw, 1)} mW`}</td>
            <td>{r.alternatives.length ? r.alternatives.map((a) => {
              const res = single(r.node, a.mode)
              const d = a.unit_power_mw_mp !== null && r.unit_power_mw_mp ? ((a.unit_power_mw_mp - r.unit_power_mw_mp) / r.unit_power_mw_mp) * 100 : null
              return <span key={a.mode} className={`mode-alt ${a.explorable ? 'on' : ''}`} title={a.explorable ? `${a.note ?? ''}\n현재 mode 대체 가능 (substitutes) → power option으로 탐색` : '기능/해상도 mode — 대체 선언(substitutes) 없음, 탐색 안 함'}>
                {a.mode} <span className="mono">{fmt(a.unit_power_mw_mp, 3)}{d !== null ? ` (${d >= 0 ? '+' : ''}${fmt(d, 0)}%)` : ''}</span>
                {res && res.delta_mw !== null && <b className="mono" style={{ color: res.delta_mw < 0 ? 'var(--primary-strong)' : 'var(--del-text)' }}> → {res.delta_mw >= 0 ? '+' : ''}{fmt(res.delta_mw, 1)} mW{res.spec_ok ? '' : ' (spec ✗)'}</b>}
                {a.explorable && !res && <span className="faint"> · 탐색 대상</span>}
              </span>
            }) : <span className="faint">—</span>}</td>
          </tr>))}</tbody>
      </table>
      <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>초록 테두리 = 현재 mode를 대체할 수 있다고 선언된 mode(substitutes) → power option으로 재시뮬레이션 · 회색 = 기능/해상도 전용 mode (참고) · → Δ = 추천 조합 대비 단독 적용 결과</div>
    </div>
  )
}

// ---------------------------------------------------------------- DVFS domain options
export function DomainLevels({ domains, chosen }: { domains: DomainRow[]; chosen: Record<string, number> }) {
  if (!domains.length) return <div className="empty">DVFS table 미연결</div>
  return (
    <table className="tb-mini-table">
      <thead><tr><th>Domain</th><th>필요 max</th><th>level 후보 (MHz · mV · ΔmW)</th></tr></thead>
      <tbody>{domains.map((d) => (
        <tr key={d.domain}>
          <td className="mono" title={d.nodes.join(', ')}>{d.domain}</td>
          <td className="mono">{fmt(d.max_required_mhz, 0)} MHz</td>
          <td>{d.options.map((o) => (
            <span key={o.level} className={`chip ${chosen[d.domain] === o.level ? 'mode-info' : ''}`} style={{ marginRight: 4 }}>
              L{o.level} {fmt(o.speed_mhz, 0)} · {fmt(o.voltage_mv, 0)}{o.raise ? ` · +${fmt(o.delta_mw, 1)}` : ''}
            </span>))}</td>
        </tr>))}</tbody>
    </table>
  )
}

// ---------------------------------------------------------------- change waterfall
export function Waterfall({ a }: { a: Attribution }) {
  const [ref, w] = useWidth<HTMLDivElement>(620)
  const steps = waterfall(a, 12)
  const labelW = 190, valW = 80, rh = 22
  const plotW = Math.max(160, w - labelW - valW)
  const vals = [a.old_total_mw, a.new_total_mw, ...steps.flatMap((s) => [s.start, s.end])]
  const lo = Math.min(...vals), hiV = Math.max(...vals)
  const pad = (hiV - lo) * 0.08 || 1
  const x0 = Math.max(0, lo - pad), x1 = hiV + pad
  const X = (v: number) => labelW + ((v - x0) / (x1 - x0)) * plotW
  const rows = [{ label: '이전', start: x0, end: a.old_total_mw, delta: 0, category: 'total' }, ...steps, { label: '현재', start: x0, end: a.new_total_mw, delta: 0, category: 'total' }]
  return (
    <div ref={ref}>
      <svg width={labelW + plotW + valW} height={rows.length * rh + 4} role="img" aria-label="power change waterfall">
        {rows.map((s, i) => {
          const total = s.category === 'total'
          const xa = X(Math.min(s.start, s.end)), xb = X(Math.max(s.start, s.end))
          const col = total ? '#3B3F4A' : CAT_COLOR[s.category] ?? '#9A9387'
          return (
            <g key={`${s.label}${i}`} transform={`translate(0,${i * rh})`}>
              <title>{total ? `${s.label} ${fmt(s.end, 1)} mW` : `${s.category} · ${s.label} ${s.delta >= 0 ? '+' : ''}${fmt(s.delta, 2)} mW`}</title>
              <text x={labelW - 6} y={15} fontSize={11} textAnchor="end" fill="#3B3F4A" className={total ? '' : 'mono'} fontWeight={total ? 600 : 400}>{s.label.length > 26 ? `${s.label.slice(0, 25)}…` : s.label}</text>
              <rect x={xa} y={4} width={Math.max(1.5, xb - xa)} height={14} fill={col} fillOpacity={total ? 0.85 : s.delta < 0 ? 0.55 : 0.9} />
              <text x={labelW + plotW + 6} y={15} fontSize={11} className="mono" fill={total ? '#3B3F4A' : s.delta < 0 ? '#2F6F68' : '#9B1C1C'}>
                {total ? fmt(s.end, 1) : `${s.delta >= 0 ? '+' : ''}${fmt(s.delta, 1)}`}</text>
            </g>
          )
        })}
      </svg>
      <div className="legend-row">
        {[...new Set(steps.map((s) => s.category))].map((c) => <span key={c} className="legend-item"><span style={{ width: 10, height: 10, background: CAT_COLOR[c] ?? '#9A9387' }} />{c}</span>)}
        <span className="faint" style={{ fontSize: 11 }}>잔차 {fmt(a.residual_mw, 3)} mW</span>
      </div>
    </div>
  )
}
