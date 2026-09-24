import { useMemo, type ReactNode } from 'react'
import { useWidth } from './Charts'
import { usePref } from './Layout'
import {
  LAT_COLOR, OVH_COLOR, STAGE_COLOR, SW_COLOR, fmt, niceMax, stageSegments,
  type FleetRow, type IpRow, type StageRow, type TimelineRow, type TimingReport, type WhatIfRow,
} from '../lib/timingBudget'

// ---------------------------------------------------------------- card
/** Resizable card: drag the bottom-right corner for height, toggle full width. Charts follow the body width. */
export function Card({ id, title, note, children, actions, defaultWide = false, minHeight = 160 }: {
  id: string; title: ReactNode; note?: ReactNode; children: ReactNode; actions?: ReactNode; defaultWide?: boolean; minHeight?: number
}) {
  const [wide, setWide] = usePref(`tb.card.${id}.wide`, defaultWide)
  return (
    <section className={`panel tb-card ${wide ? 'wide' : ''}`} aria-label={typeof title === 'string' ? title : id} style={{ minHeight }}>
      <div className="tb-card-head">
        <h2>{title}</h2>
        {note && <span className="faint tb-note">{note}</span>}
        <span className="grow" />
        {actions}
        <button className="btn tb-mini wide-toggle" onClick={() => setWide((w) => !w)} title={wide ? '반폭으로' : '전체 폭으로'} aria-label={wide ? '반폭으로' : '전체 폭으로'}>{wide ? '⇤⇥' : '⇔'}</button>
      </div>
      <div className="tb-card-body">{children}</div>
    </section>
  )
}

// ---------------------------------------------------------------- ① slot budget
export function SlotBudget({ report }: { report: TimingReport }) {
  const [ref, w] = useWidth<HTMLDivElement>(900)
  const P = report.period_ms
  const labelW = 150, valW = 150
  const barW = Math.max(200, w - labelW - valW - 24)
  const px = barW / P
  const rows = report.stages
  return (
    <div ref={ref} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {rows.map((s) => <SlotRow key={s.id} stage={s} P={P} px={px} barW={barW} labelW={labelW} valW={valW} />)}
      <div className="legend-row" style={{ paddingLeft: labelW + 12 }}>
        <Legend color={STAGE_COLOR.rt} label="RT HW" /><Legend color={STAGE_COLOR.nrt} label="NRT HW" /><Legend color={STAGE_COLOR.post} label="GDC HW" />
        <Legend color={STAGE_COLOR.output} label="Output HW" /><Legend color={SW_COLOR} label="SW runtime" /><Legend color={LAT_COLOR} label="SW latency" />
        <Legend color={OVH_COLOR} label="IP driver/IRQ" /><Legend color="#FCEFD6" border="#E5C48A" label="RT SW margin 25%" />
        <span className="legend-item"><span style={{ width: 2, height: 12, background: 'var(--text)' }} />frame period</span>
      </div>
    </div>
  )
}

function SlotRow({ stage, P, px, barW, labelW, valW }: { stage: StageRow; P: number; px: number; barW: number; labelW: number; valW: number }) {
  const segs = stageSegments(stage)
  let x = 0
  const used = segs.reduce((a, s) => a + s.ms, 0)
  const over = used > P * 1.0005 || !stage.feasible
  const sub = stage.id === 'rt' ? 'sensor 동기 · 25% rule' : stage.id === 'nrt' ? 'MTNR→MCSC · SW gating 반영' : stage.id === 'post' ? 'memory → EIS/SW → GDC' : 'DPU · MFC · writer (25% rule)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <div style={{ width: labelW, flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{stage.name}</div>
        <div className="faint" style={{ fontSize: 11 }}>{sub}</div>
      </div>
      <svg width={barW} height={40} role="img" aria-label={`${stage.name} slot`} style={{ overflow: 'visible', flexShrink: 0 }}>
        <rect x={0} y={6} width={barW} height={28} fill="#F7F4EF" rx={3} />
        {stage.id === 'rt' && <rect x={stage.budget_ms * px} y={6} width={(P - stage.budget_ms) * px} height={28} fill="#FCEFD6" stroke="#E5C48A" />}
        {segs.map((s) => {
          const w = Math.max(1, Math.min(s.ms, P * 1.5 - x) * px)
          const el = (
            <g key={s.key}>
              <title>{s.tip}</title>
              <rect x={x * px} y={6} width={w} height={28} fill={s.color} stroke="#FFFFFF" strokeWidth={1} />
              {w > 44 && <text x={x * px + w / 2} y={24} textAnchor="middle" fontSize={11} fill={s.text}>{s.label}</text>}
            </g>
          )
          x += s.ms
          return el
        })}
        {stage.id !== 'rt' && stage.budget_ms > 0 && stage.budget_ms < P && (
          <line x1={(P - stage.budget_ms) * px} x2={(P - stage.budget_ms) * px} y1={2} y2={38} stroke="#3B3F4A" strokeDasharray="3 3"><title>HW 예산 시작 (period − SW)</title></line>
        )}
        {stage.id === 'rt' && <line x1={stage.budget_ms * px} x2={stage.budget_ms * px} y1={0} y2={40} stroke="#7A4B12" strokeDasharray="4 3" strokeWidth={1.5} />}
        <line x1={barW} x2={barW} y1={0} y2={40} stroke="var(--text)" strokeWidth={2} />
      </svg>
      <div className="mono" style={{ width: valW, flexShrink: 0, fontSize: 12, textAlign: 'right', color: over ? 'var(--del-text)' : 'var(--text-2)' }}>
        {stage.id === 'rt' || stage.id === 'output'
          ? `HW ${fmt(stage.hw_ms, 2)} / ${fmt(stage.budget_ms, 2)}`
          : `SW ${fmt(stage.sw_ms, 2)} + HW ${fmt(stage.hw_ms, 2)}`}
        <div className="faint" style={{ fontSize: 11 }}>{stage.feasible ? `${fmt(stage.fill_pct, 0)}% of ${fmt(P, 2)} ms` : 'HW 예산 없음'}</div>
      </div>
    </div>
  )
}

function Legend({ color, label, border }: { color: string; label: string; border?: string }) {
  return <span className="legend-item"><span style={{ width: 14, height: 10, background: color, border: border ? `1px solid ${border}` : undefined, borderRadius: 2 }} />{label}</span>
}

// ---------------------------------------------------------------- ⑤ clocks
export function ClockChart({ ips }: { ips: IpRow[] }) {
  const [ref, w] = useWidth<HTMLDivElement>(600)
  const rows = ips.filter((i) => i.set_clock_mhz > 0)
  const max = niceMax(Math.max(...rows.map((i) => Math.max(i.set_clock_mhz, i.rule_clock_mhz ?? 0))))
  const labelW = 132, valW = 190
  const barW = Math.max(120, w - labelW - valW - 16)
  return (
    <div ref={ref} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {rows.map((ip) => {
        const up = ip.rule_clock_mhz !== null && ip.set_clock_mhz > ip.rule_clock_mhz + 0.5
        return (
          <div key={ip.node} style={{ display: 'flex', alignItems: 'center', gap: 8 }} title={ip.clock_reason ?? undefined}>
            <div style={{ width: labelW, flexShrink: 0, display: 'flex', gap: 6, alignItems: 'baseline' }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: STAGE_COLOR[ip.stage], flexShrink: 0 }} />
              <b style={{ fontSize: 12 }}>{ip.node.toUpperCase()}</b>
              <span className="faint" style={{ fontSize: 11 }}>{ip.dvfs_group ?? ''}{ip.cores > 1 ? ` ×${ip.cores}` : ''}{ip.shared_streams > 1 ? ` ⇄${ip.shared_streams}` : ''}</span>
            </div>
            <svg width={barW} height={20} style={{ flexShrink: 0 }} role="img" aria-label={`${ip.node} clock`}>
              <rect x={0} y={1} width={barW} height={18} fill="#FBFAF7" />
              {ip.rule_clock_mhz !== null && <rect x={0} y={2} width={(ip.rule_clock_mhz / max) * barW} height={7} fill="#DED8CF"><title>25% rule {fmt(ip.rule_clock_mhz)} MHz</title></rect>}
              <rect x={0} y={11} width={(ip.set_clock_mhz / max) * barW} height={7} fill={up ? '#C2410C' : '#2F6F68'}><title>set {fmt(ip.set_clock_mhz)} MHz (required {fmt(ip.required_clock_mhz)})</title></rect>
              {ip.required_clock_mhz < ip.set_clock_mhz - 0.5 && <line x1={(ip.required_clock_mhz / max) * barW} x2={(ip.required_clock_mhz / max) * barW} y1={9} y2={20} stroke="#1F2430" strokeWidth={1.5}><title>required {fmt(ip.required_clock_mhz)} MHz</title></line>}
            </svg>
            <span className="mono" style={{ width: valW, flexShrink: 0, fontSize: 12, color: up ? '#C2410C' : 'var(--text-2)' }}>
              {fmt(ip.rule_clock_mhz, 0)} → {fmt(ip.set_clock_mhz, 0)} MHz{ip.dvfs_level !== null ? ` · L${ip.dvfs_level} ${fmt(ip.voltage_mv, 0)}mV` : ''}
            </span>
          </div>
        )
      })}
      <div className="legend-row" style={{ paddingLeft: labelW + 8 }}>
        <Legend color="#DED8CF" label="25% rule" /><Legend color="#2F6F68" label="Timing budget" /><Legend color="#C2410C" label="rule 대비 상승" />
        <span className="legend-item"><span style={{ width: 2, height: 10, background: '#1F2430' }} />required (DVFS level 선택 전)</span>
        <span className="faint" style={{ fontSize: 11 }}>×2 = MFC+MFD 병렬 · ⇄2 = 2 stream 공유</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- ⑥ power / BW
export function PowerBw({ report }: { report: TimingReport }) {
  const [ref, w] = useWidth<HTMLDivElement>(600)
  const p = report.power, bw = report.bw
  const barW = Math.max(200, w - 8)
  const parts = [
    { key: 'CPU (SW)', v: p.cpu_mw, c: SW_COLOR },
    { key: 'HW IP core', v: p.hw_mw, c: STAGE_COLOR.rt },
    { key: 'BW · MIF', v: p.bw_mw, c: STAGE_COLOR.nrt },
  ]
  const ipRows = Object.entries(p.hw_by_ip).filter(([, v]) => v > 0)
  const cpuRows = Object.entries(p.cpu_by_task).filter(([, v]) => v > 0)
  const bwRows = [...Object.entries(bw.hw_by_ip).map(([k, v]) => ({ k, v, sw: false })), ...Object.entries(bw.sw_by_task).map(([k, v]) => ({ k, v, sw: true }))].sort((a, b) => b.v - a.v)
  const bwMax = niceMax(Math.max(1, ...bwRows.map((r) => r.v)))
  const pMax = niceMax(Math.max(1, ...ipRows.map(([, v]) => v), ...cpuRows.map(([, v]) => v)))
  return (
    <div ref={ref} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8 }}>
        <Tile label="Total" value={`${fmt(p.total_mw)} mW`} note={`CPU ${fmt(p.share_pct.cpu, 0)}% · HW ${fmt(p.share_pct.hw, 0)}% · BW ${fmt(p.share_pct.bw, 0)}%`} />
        <Tile label="CPU (SW)" value={`${fmt(p.cpu_mw)} mW`} note={`${fmt(p.cpu_busy_ms, 1)} ms/frame · CL${p.cpu_model.cluster} ${p.cpu_model.freq_mhz} MHz ${p.cpu_model.volt_v} V`} />
        <Tile label="HW IP core" value={`${fmt(p.hw_mw)} mW`} note={p.zero_power_ips.length ? `unit_power=0: ${p.zero_power_ips.join(', ')}` : '전 IP 계수 있음'} />
        <Tile label="DMA BW" value={`${fmt(bw.total_mbs / 1000, 2)} GB/s`} note={`HW ${fmt(bw.share_pct.hw, 1)}% · SW ${fmt(bw.share_pct.sw, 1)}% · MIF ${fmt(p.bw_mw)} mW`} />
      </div>
      <div>
        <div className="faint" style={{ fontSize: 12, marginBottom: 4 }}>전력 구성 (mW, 비중)</div>
        <svg width={barW} height={26} role="img" aria-label="전력 구성">
          {(() => { let x = 0; return parts.map((s) => { const wpx = (s.v / Math.max(p.total_mw, 1e-9)) * barW; const g = (
            <g key={s.key}><title>{`${s.key} ${fmt(s.v)} mW`}</title><rect x={x} y={0} width={Math.max(0, wpx)} height={26} fill={s.c} stroke="#FFFFFF" />
              {wpx > 90 && <text x={x + wpx / 2} y={17} textAnchor="middle" fontSize={11} fill="#FFFFFF">{s.key} {fmt(s.v, 0)} ({fmt((s.v / p.total_mw) * 100, 0)}%)</text>}</g>); x += wpx; return g }) })()}
        </svg>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 16 }}>
        <HBarList title="HW IP core power (mW)" rows={ipRows.map(([k, v]) => ({ k: k.toUpperCase(), v, c: STAGE_COLOR.rt }))} max={pMax} unit="mW" />
        <HBarList title="CPU SW task power (mW)" rows={cpuRows.map(([k, v]) => ({ k, v, c: SW_COLOR }))} max={pMax} unit="mW" />
      </div>
      <HBarList title={`DMA BW by IP / SW (MB/s) · HW ${fmt(bw.hw_mbs, 0)} · SW ${fmt(bw.sw_mbs, 0)}`} rows={bwRows.map((r) => ({ k: r.sw ? `${r.k} (SW)` : r.k.toUpperCase(), v: r.v, c: r.sw ? SW_COLOR : STAGE_COLOR.nrt }))} max={bwMax} unit="MB/s" />
      <div className="faint" style={{ fontSize: 11 }}>CPU = {p.cpu_model.source} · BW 전력 = MIF (bw_power_coeff) · DVFS: {report.dvfs.applied ? `${report.dvfs.table_ref ?? report.dvfs.tables.join(',')} (전압 반영)` : '미연결 (전압 고정)'}</div>
    </div>
  )
}

function Tile({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div style={{ background: 'var(--surface-soft)', border: '1px solid var(--line-soft)', borderRadius: 6, padding: '8px 10px', minWidth: 0 }}>
      <div className="faint" style={{ fontSize: 11 }}>{label}</div>
      <div className="mono" style={{ fontSize: 17, fontWeight: 600 }}>{value}</div>
      <div className="faint" style={{ fontSize: 11, lineHeight: 1.35, overflowWrap: 'anywhere' }} title={note}>{note}</div>
    </div>
  )
}

function HBarList({ title, rows, max, unit }: { title: string; rows: { k: string; v: number; c: string }[]; max: number; unit: string }) {
  const [ref, w] = useWidth<HTMLDivElement>(300)
  const labelW = 110, valW = 76
  const barW = Math.max(60, w - labelW - valW - 12)
  return (
    <div ref={ref} style={{ minWidth: 0 }}>
      <div className="faint" style={{ fontSize: 12, marginBottom: 4 }}>{title}</div>
      {rows.length === 0 && <div className="faint" style={{ fontSize: 12 }}>—</div>}
      {rows.map((r) => (
        <div key={r.k} style={{ display: 'flex', alignItems: 'center', gap: 6, height: 18 }}>
          <span style={{ width: labelW, fontSize: 12, textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.k}>{r.k}</span>
          <svg width={barW} height={12} style={{ flexShrink: 0 }}><rect x={0} y={1} width={(r.v / max) * barW} height={10} fill={r.c} rx={1} /></svg>
          <span className="mono" style={{ width: valW, fontSize: 11 }}>{fmt(r.v, r.v < 10 ? 2 : 0)} {unit}</span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- ② timeline
const LANES: { id: string; name: string; match: (r: TimelineRow) => boolean }[] = [
  { id: 'rt', name: 'RT HW', match: (r) => r.stage === 'rt' && r.type === 'hw' },
  { id: 'nrtsw', name: 'NRT SW', match: (r) => r.stage === 'nrt' && r.type === 'sw' },
  { id: 'nrt', name: 'NRT HW', match: (r) => r.stage === 'nrt' && r.type === 'hw' },
  { id: 'postsw', name: 'EIS / SW', match: (r) => r.stage === 'post' && r.type === 'sw' },
  { id: 'post', name: 'GDC', match: (r) => r.stage === 'post' && r.type === 'hw' },
  { id: 'dpu', name: 'DPU (preview)', match: (r) => r.stage === 'output' && r.type === 'hw' && /dpu/i.test(r.node) },
  { id: 'enc', name: 'MFC (video)', match: (r) => r.stage === 'output' && r.type === 'hw' && /(mfc|apv)/i.test(r.node) },
  { id: 'wsw', name: 'Writer SW', match: (r) => r.stage === 'output' && r.type === 'sw' },
]

export function Gantt({ report }: { report: TimingReport }) {
  const [ref, w] = useWidth<HTMLDivElement>(900)
  const rows = report.timeline
  const end = Math.max(1, ...rows.map((r) => r.end_ms))
  const labelW = 110
  const plotW = Math.max(300, w - labelW - 8)
  const k = plotW / end
  const P = report.period_ms
  const lanes = useMemo(() => LANES.map((l) => {
    // RT/NRT HW lanes: per frame, union of the stage's HW node intervals (parallel IPs collapse to one bar).
    const grouped = l.id === 'rt' || l.id === 'nrt'
    const hit = rows.filter(l.match)
    let bars: TimelineRow[]
    if (grouped) {
      bars = []
      const frames = [...new Set(hit.map((r) => r.frame))]
      for (const f of frames) {
        const iv = hit.filter((r) => r.frame === f).sort((x, y) => x.start_ms - y.start_ms)
        let cur: TimelineRow | null = null
        const names: string[] = []
        for (const r of iv) {
          if (cur && r.start_ms <= cur.end_ms + 1e-6) { cur.end_ms = Math.max(cur.end_ms, r.end_ms); names.push(r.node); cur.node = names.join(', '); continue }
          if (cur) bars.push(cur)
          names.length = 0; names.push(r.node)
          cur = { ...r }
        }
        if (cur) bars.push(cur)
      }
    } else {
      const seen = new Set<string>()
      bars = hit.filter((r) => { const key = `${r.frame}:${r.node}`; if (seen.has(key)) return false; seen.add(key); return true })
    }
    return { ...l, bars }
  }).filter((l) => l.bars.length), [rows])
  const ticks = Array.from({ length: Math.floor(end / P) + 1 }, (_, i) => i * P)
  return (
    <div ref={ref}>
      <svg width={labelW + plotW} height={lanes.length * 24 + 22} role="img" aria-label="pipeline timeline">
        {ticks.map((t, i) => <g key={i}><line x1={labelW + t * k} x2={labelW + t * k} y1={14} y2={lanes.length * 24 + 18} stroke="#C9C1B4" strokeDasharray="2 3" /><text x={labelW + t * k + 2} y={10} fontSize={10} fill="#8A8274">f{i} {fmt(t, 0)}ms</text></g>)}
        {lanes.map((l, li) => (
          <g key={l.id} transform={`translate(0, ${16 + li * 24})`}>
            <text x={labelW - 6} y={14} textAnchor="end" fontSize={11} fill="#3B3F4A">{l.name}</text>
            <rect x={labelW} y={1} width={plotW} height={20} fill="#FBFAF7" />
            {l.bars.map((b, i) => {
              const color = l.id.includes('sw') ? SW_COLOR : STAGE_COLOR[b.stage]
              const bw = Math.max(1.5, (b.end_ms - b.start_ms) * k)
              return (
                <g key={i}>
                  <title>{`${b.node} f${b.frame} · ${fmt(b.start_ms, 2)} → ${fmt(b.end_ms, 2)} ms`}</title>
                  <rect x={labelW + b.start_ms * k} y={3} width={bw} height={16} fill={color} opacity={b.frame % 2 ? 0.62 : 1} rx={2} />
                  {bw > 22 && <text x={labelW + b.start_ms * k + bw / 2} y={15} textAnchor="middle" fontSize={10} fill="#FFFFFF">f{b.frame}</text>}
                </g>
              )
            })}
          </g>
        ))}
      </svg>
    </div>
  )
}

// ---------------------------------------------------------------- ③ intervals
export function Intervals({ report }: { report: TimingReport }) {
  const [ref, w] = useWidth<HTMLDivElement>(600)
  const t = report.intervals.target_ms, tol = report.intervals.tolerance
  const series = [
    { key: 'Preview', s: report.intervals.preview, c: STAGE_COLOR.rt, lat: report.latency.preview_ms, lf: report.latency.preview_frames },
    { key: 'Video', s: report.intervals.video, c: STAGE_COLOR.output, lat: report.latency.video_ms, lf: report.latency.video_frames },
  ].filter((x) => x.s.node)
  const all = series.flatMap((x) => x.s.values)
  const span = Math.max(t * 0.01, ...all.map((v) => Math.abs(v - t))) * 1.3
  const H = 80, plotW = Math.max(200, w - 8)
  const y = (v: number) => H / 2 - ((v - t) / span) * (H / 2 - 6)
  return (
    <div ref={ref} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {series.map((x) => {
        const n = x.s.values.length
        return (
          <div key={x.key}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 13 }}>
              <b>{x.key}</b><span className="faint mono" style={{ fontSize: 12 }}>{x.s.node}</span>
              <span className="mono" style={{ fontSize: 12, color: x.s.ok ? 'var(--primary-strong)' : 'var(--del-text)' }}>
                {x.s.ok ? '✓' : '✗'} max {fmt(x.s.max_ms, 3)} · min {fmt(x.s.min_ms, 3)} ms (±{fmt(tol * 100, 1)}%)
              </span>
              <span className="grow" />
              <span className="mono" style={{ fontSize: 12 }}>latency {fmt(x.lat, 1)} ms ({fmt(x.lf, 2)} frame)</span>
            </div>
            <svg width={plotW} height={H} role="img" aria-label={`${x.key} interval`}>
              <rect x={0} y={0} width={plotW} height={H} fill="#FBFAF7" />
              <rect x={0} y={y(t * (1 + tol))} width={plotW} height={Math.max(1, y(t * (1 - tol)) - y(t * (1 + tol)))} fill="#E3EEEB" />
              <line x1={0} x2={plotW} y1={y(t)} y2={y(t)} stroke="#2F6F68" strokeDasharray="4 3" />
              <text x={plotW - 4} y={y(t) - 4} textAnchor="end" fontSize={10} fill="#2F6F68">target {fmt(t, 3)} ms</text>
              {x.s.values.map((v, i) => {
                const bad = Math.abs(v - t) > t * tol
                return <circle key={i} cx={16 + (i * (plotW - 32)) / Math.max(1, n - 1)} cy={Math.max(5, Math.min(H - 5, y(v)))} r={4.5} fill={bad ? '#7F1D1D' : x.c}><title>{`f${i + 1}: ${fmt(v, 3)} ms`}</title></circle>
              })}
            </svg>
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------- ④ what-if
export function WhatIf({ rows, current }: { rows: WhatIfRow[]; current: { statistic: string; eis: boolean; scale: number } }) {
  const [ref, w] = useWidth<HTMLDivElement>(600)
  const plotW = Math.max(260, w - 60), H = 220
  const scales = [...new Set(rows.map((r) => r.scale))].sort((a, b) => a - b)
  const vals = rows.map((r) => r.nrt_clock_mhz ?? 0)
  const rule = rows.find((r) => r.nrt_rule_clock_mhz)?.nrt_rule_clock_mhz ?? 0
  const max = niceMax(Math.max(rule, ...vals))
  const x = (s: number) => 50 + ((s - scales[0]) / Math.max(1e-9, scales[scales.length - 1] - scales[0])) * (plotW - 10)
  const y = (v: number) => H - 24 - (v / max) * (H - 40)
  const lines = [
    { stat: 'max', eis: true, c: '#C2410C', dash: '' }, { stat: 'max', eis: false, c: '#C2410C', dash: '6 4' },
    { stat: 'mean', eis: true, c: '#2F6F68', dash: '' }, { stat: 'mean', eis: false, c: '#2F6F68', dash: '6 4' },
  ]
  const cur = rows.find((r) => r.statistic === current.statistic && r.eis === current.eis && Math.abs(r.scale - current.scale) < 1e-6)
  return (
    <div ref={ref}>
      <svg width={plotW + 60} height={H} role="img" aria-label="SW 증가 대비 NRT clock">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => <g key={f}><line x1={50} x2={plotW + 40} y1={y(max * f)} y2={y(max * f)} stroke="#EFEAE2" /><text x={44} y={y(max * f) + 3} textAnchor="end" fontSize={10} fill="#8A8274">{fmt(max * f, 0)}</text></g>)}
        {scales.map((s) => <text key={s} x={x(s)} y={H - 6} textAnchor="middle" fontSize={10} fill="#8A8274">×{s.toFixed(1)}</text>)}
        {rule > 0 && <><line x1={50} x2={plotW + 40} y1={y(rule)} y2={y(rule)} stroke="#7A4B12" strokeDasharray="5 4" /><text x={plotW + 40} y={y(rule) - 4} textAnchor="end" fontSize={10} fill="#7A4B12">25% rule {fmt(rule, 0)} MHz</text></>}
        {lines.map((l) => {
          const pts = rows.filter((r) => r.statistic === l.stat && r.eis === l.eis).sort((a, b) => a.scale - b.scale)
          return <g key={`${l.stat}${l.eis}`}>
            <polyline points={pts.map((r) => `${x(r.scale)},${y(r.nrt_clock_mhz ?? 0)}`).join(' ')} fill="none" stroke={l.c} strokeWidth={2.2} strokeDasharray={l.dash} />
            {pts.filter((r) => r.verdict.status === 'fail').map((r) => <circle key={r.scale} cx={x(r.scale)} cy={y(r.nrt_clock_mhz ?? 0)} r={4} fill="#7F1D1D"><title>fail: {r.verdict.reasons[0]}</title></circle>)}
          </g>
        })}
        {cur && <circle cx={x(cur.scale)} cy={y(cur.nrt_clock_mhz ?? 0)} r={6} fill="#1F2430" stroke="#FFFFFF" strokeWidth={2} />}
      </svg>
      <div className="legend-row">
        <span className="legend-item"><span style={{ width: 18, borderTop: '3px solid #C2410C' }} />max · EIS on</span>
        <span className="legend-item"><span style={{ width: 18, borderTop: '2px dashed #C2410C' }} />max · EIS off</span>
        <span className="legend-item"><span style={{ width: 18, borderTop: '3px solid #2F6F68' }} />mean · EIS on</span>
        <span className="legend-item"><span style={{ width: 18, borderTop: '2px dashed #2F6F68' }} />mean · EIS off</span>
        <span className="legend-item"><span style={{ width: 8, height: 8, borderRadius: 4, background: '#7F1D1D' }} />fail</span>
      </div>
      {cur && <div className="mono" style={{ fontSize: 12, marginTop: 4 }}>현재 {current.statistic} · EIS {current.eis ? 'on' : 'off'} · ×{current.scale.toFixed(1)} → {cur.nrt_driver?.toUpperCase()} {fmt(cur.nrt_clock_mhz, 0)} MHz · NRT SW {fmt(cur.stages.nrt.sw_ms, 1)} ms · HW 예산 {fmt(cur.stages.nrt.budget_ms, 1)} ms · {cur.interval_ok ? '간격 OK' : '간격 ✗'}</div>}
    </div>
  )
}

// ---------------------------------------------------------------- fleet ranking
/** Ranked dumbbell: one row per variant (rule clock → required clock), sorted by factor. Never overlaps. */
export function FleetRank({ rows, onPick, limit }: { rows: FleetRow[]; onPick: (v: string) => void; limit: number }) {
  const [ref, w] = useWidth<HTMLDivElement>(800)
  const data = rows.map((r) => ({ r, rule: r.clocks.nrt.rule_mhz ?? 0, set: r.clocks.nrt.set_mhz ?? 0, sw: r.stages.nrt.sw_ms / r.period_ms }))
    .sort((a, b) => (b.set / Math.max(b.rule, 1e-9)) - (a.set / Math.max(a.rule, 1e-9))).slice(0, limit)
  const labelW = 200, swW = 110, valW = 150
  const plotW = Math.max(160, w - labelW - swW - valW - 24)
  const max = niceMax(Math.max(1, ...data.map((d) => Math.max(d.rule, d.set))))
  const x = (v: number) => (v / max) * plotW
  return (
    <div ref={ref} style={{ display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', gap: 8, fontSize: 11 }} className="faint">
        <span style={{ width: labelW }}>Variant</span><span style={{ width: plotW }}>NRT 필요 clock (MHz) · ○ 25% rule → ● timing budget</span>
        <span style={{ width: swW }}>NRT SW / period</span><span style={{ width: valW }}>배율 · level</span>
      </div>
      {data.map(({ r, rule, set, sw }) => {
        const color = r.verdict.status === 'fail' ? '#7F1D1D' : set > rule * 1.05 ? '#C2410C' : '#2F6F68'
        return (
          <button key={r.variant_id} className="tb-rank-row" onClick={() => onPick(r.variant_id)} title={`${r.variant_id} · ${r.verdict.reasons[0] ?? r.verdict.status}`}>
            <span className="mono" style={{ width: labelW, textAlign: 'left', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.variant_id.replace(/^cam-rec-/, '')}</span>
            <svg width={plotW} height={18} style={{ flexShrink: 0 }}>
              <rect x={0} y={8} width={plotW} height={2} fill="#EFEAE2" />
              <line x1={x(Math.min(rule, set))} x2={x(Math.max(rule, set))} y1={9} y2={9} stroke={color} strokeWidth={3} />
              <circle cx={x(rule)} cy={9} r={5} fill="#FFFFFF" stroke="#8A8274" strokeWidth={1.5} />
              <circle cx={x(set)} cy={9} r={5} fill={color} />
            </svg>
            <svg width={swW} height={12} style={{ flexShrink: 0 }}><rect x={0} y={1} width={swW} height={10} fill="#F7F4EF" /><rect x={0} y={1} width={Math.min(1, sw) * swW} height={10} fill={SW_COLOR} /></svg>
            <span className="mono" style={{ width: valW, textAlign: 'left', color }}>×{fmt(rule ? set / rule : null, 2)} · {fmt(set, 0)} MHz{r.clocks.nrt.level !== null ? ` L${r.clocks.nrt.level}` : ''}</span>
          </button>
        )
      })}
      <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>axis 0–{fmt(max, 0)} MHz · 정렬 = 배율 내림차순 · 행 클릭 = variant 상세</div>
    </div>
  )
}
