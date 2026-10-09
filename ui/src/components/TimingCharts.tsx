import { useMemo, useState, type ReactNode } from 'react'
import { useWidth } from './Charts'
import { useTip } from './ChartTip'
import { usePref } from './Layout'
import {
  LAT_COLOR, OVH_COLOR, SET_REASON_LABEL, STAGE_COLOR, SW_COLOR, basisLabel, breakEven, clockText, cpuTileNote, domainOf, fmt, niceMax, otfPacers, pct0, stageSegments, whatIfDomains,
  type FleetRow, type IpRow, type StageRow, type TimelineRow, type TimingReport, type WhatIfRow,
} from '../lib/timingBudget'

// ---------------------------------------------------------------- card
/** Resizable card: drag the bottom-right corner for height, toggle full width. Charts follow the body width. */
export function Card({ id, title, note, children, actions, defaultWide = false, minHeight = 160, help }: {
  id: string; title: ReactNode; note?: ReactNode; children: ReactNode; actions?: ReactNode; defaultWide?: boolean; minHeight?: number
  /** "?" button → explanation panel (what the card means, how to read / use it) */
  help?: ReactNode
}) {
  const [wide, setWide] = usePref(`tb.card.${id}.wide`, defaultWide)
  const [showHelp, setShowHelp] = useState(false)
  return (
    <section className={`panel tb-card ${wide ? 'wide' : ''}`} aria-label={typeof title === 'string' ? title : id} style={{ minHeight }}>
      <div className="tb-card-head">
        <h2>{title}</h2>
        {help && <button className={`help-q ${showHelp ? 'on' : ''}`} onClick={() => setShowHelp((v) => !v)} aria-label="도움말" aria-expanded={showHelp} title="이 카드 설명">?</button>}
        {note && <span className="faint tb-note">{note}</span>}
        <span className="grow" />
        {actions}
        <button className="btn tb-mini wide-toggle" onClick={() => setWide((w) => !w)} title={wide ? '반폭으로' : '전체 폭으로'} aria-label={wide ? '반폭으로' : '전체 폭으로'}>{wide ? '⇤⇥' : '⇔'}</button>
      </div>
      {help && showHelp && <div className="help-panel">{help}</div>}
      <div className="tb-card-body">{children}</div>
    </section>
  )
}

// ---------------------------------------------------------------- ① slot budget
export function SlotBudget({ report, margin = 0.25 }: { report: TimingReport; margin?: number }) {
  const [ref, w] = useWidth<HTMLDivElement>(900)
  const P = report.period_ms
  const labelW = 150, valW = 150
  const barW = Math.max(200, w - labelW - valW - 24)
  const px = barW / P
  const rows = report.stages
  return (
    <div ref={ref} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {rows.map((s) => <SlotRow key={s.id} stage={s} P={P} px={px} barW={barW} labelW={labelW} valW={valW} margin={margin} />)}
      <div className="legend-row" style={{ paddingLeft: labelW + 12 }}>
        <Legend color={STAGE_COLOR.rt} label="RT HW" /><Legend color={STAGE_COLOR.nrt} label="NRT HW" /><Legend color={STAGE_COLOR.post} label="GDC HW" />
        <Legend color={STAGE_COLOR.output} label="Output HW" /><Legend color={SW_COLOR} label="SW runtime" /><Legend color={LAT_COLOR} label="SW latency" />
        <Legend color={OVH_COLOR} label="IP driver/IRQ" /><Legend color="#FCEFD6" border="#E5C48A" label={`RT · Output SW margin ${pct0(margin)}`} />
        <span className="legend-item"><span style={{ width: 2, height: 12, background: 'var(--text)' }} />frame period</span>
      </div>
    </div>
  )
}

function SlotRow({ stage, P, px, barW, labelW, valW, margin }: { stage: StageRow; P: number; px: number; barW: number; labelW: number; valW: number; margin: number }) {
  const tip = useTip()
  const segs = stageSegments(stage)
  let x = 0
  const used = segs.reduce((a, s) => a + s.ms, 0)
  // pipelined NRT / Post: SW and HW run on different frames through M2M buffers — a chain > period only adds latency
  const piped = stage.throughput === 'pipelined' && (stage.id === 'nrt' || stage.id === 'post')
  const over = piped ? !stage.feasible : used > P * 1.0005 || !stage.feasible
  const extraFrames = piped && used > P * 1.0005 ? Math.ceil(used / P) - 1 : 0
  const sub = stage.id === 'rt' ? `sensor readout 종속 · ${pct0(margin)} rule은 판정만` : stage.id === 'nrt' ? 'MTNR→MCSC · SW gating 반영' : stage.id === 'post' ? 'memory → EIS/SW → GDC' : `DPU · MFC · writer (${pct0(margin)} rule)`
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
          const w = Math.max(1, Math.min(s.ms, (piped ? P : P * 1.5) - x) * px)
          if ((piped ? P : P * 1.5) - x <= 0) { x += s.ms; return null }
          const el = (
            <g key={s.key} {...tip({ title: s.label, color: s.color, head: { label: '소요', value: `${fmt(s.ms, 2)} ms`, tone: 'strong' },
              rows: [{ k: 'frame 주기 대비', v: `${fmt((s.ms / P) * 100, 1)}% of ${fmt(P, 2)} ms` }, { k: 'slot 시작', v: `+${fmt(x, 2)} ms` }], foot: s.tip })}>
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
        {extraFrames > 0 && <g><rect x={barW - 46} y={8} width={42} height={24} rx={4} fill="#FFFFFF" opacity={0.9} /><text x={barW - 25} y={24} textAnchor="middle" fontSize={11} fontWeight={700} fill="#7A4B12">+{extraFrames}f ▶</text>
          <title>{`SW+HW ${fmt(used, 2)} ms > frame ${fmt(P, 2)} ms — 남은 부분은 다음 frame 구간에서 처리 (buffering, latency +${extraFrames} frame)`}</title></g>}
      </svg>
      <div className="mono" style={{ width: valW, flexShrink: 0, fontSize: 12, textAlign: 'right', color: over ? 'var(--del-text)' : 'var(--text-2)' }}>
        {stage.id === 'rt' || stage.id === 'output'
          ? `HW ${fmt(stage.hw_ms, 2)} / ${fmt(stage.budget_ms, 2)}`
          : `SW ${fmt(stage.sw_ms, 2)} + HW ${fmt(stage.hw_ms, 2)}`}
        <div className="faint" style={{ fontSize: 11 }}>{!stage.feasible ? (piped ? `최장 SW ${fmt(stage.longest_sw_ms ?? 0, 2)} > frame` : 'HW 예산 없음')
          : extraFrames ? `${fmt((used / P) * 100, 0)}% · pipeline → latency +${extraFrames} frame` : `${fmt(stage.fill_pct, 0)}% of ${fmt(P, 2)} ms`}</div>
      </div>
    </div>
  )
}

function Legend({ color, label, border }: { color: string; label: string; border?: string }) {
  return <span className="legend-item"><span style={{ width: 14, height: 10, background: color, border: border ? `1px solid ${border}` : undefined, borderRadius: 2 }} />{label}</span>
}

// ---------------------------------------------------------------- ⑤ clocks
const DOMAIN_TINT = ['#EEF4FB', '#F2F7EE', '#FBF3EA', '#F4EFFA', '#EEF7F6', '#FAF0F2']
const DOMAIN_EDGE = ['#7FA7D6', '#8FBF7A', '#E0A867', '#A88BD0', '#6FB8AE', '#D98A9C']
const STAGE_RANK: Record<string, number> = { rt: 0, nrt: 1, post: 2, output: 3 }

/** IPs grouped by DVFS domain (one voltage per domain → the most demanding IP sets the domain level). */
export function domainGroups(ips: IpRow[]): { domain: string; rows: IpRow[]; level: number | null; voltage: number; driver: IpRow }[] {
  const by = new Map<string, IpRow[]>()
  for (const ip of ips.filter((i) => i.set_clock_mhz > 0)) {
    const d = ip.dvfs_group ?? '(domain 없음)'
    by.set(d, [...(by.get(d) ?? []), ip])
  }
  return [...by.entries()].map(([domain, rows]) => {
    const sorted = [...rows].sort((a, b) => (STAGE_RANK[a.stage] ?? 9) - (STAGE_RANK[b.stage] ?? 9) || a.node.localeCompare(b.node))
    const lv = rows.map((r) => r.dvfs_level).filter((l): l is number => l !== null)
    const need = (r: IpRow) => r.own_required_mhz ?? r.required_clock_mhz
    const driver = [...rows].sort((a, b) => need(b) - need(a) || (b.hw_ms ?? 0) - (a.hw_ms ?? 0))[0]
    return { domain, rows: sorted, level: lv.length ? Math.max(...lv) : null, voltage: Math.max(...rows.map((r) => r.voltage_mv)), driver }
  }).sort((a, b) => Math.min(...a.rows.map((r) => STAGE_RANK[r.stage] ?? 9)) - Math.min(...b.rows.map((r) => STAGE_RANK[r.stage] ?? 9)) || a.domain.localeCompare(b.domain))
}

export function ClockChart({ ips, dvfsApplied = true, margin = 0.25 }: { ips: IpRow[]; dvfsApplied?: boolean; margin?: number }) {
  const [ref, w] = useWidth<HTMLDivElement>(600)
  const tip = useTip()
  const rows = ips.filter((i) => i.set_clock_mhz > 0)
  const max = niceMax(Math.max(...rows.map((i) => Math.max(i.set_clock_mhz, i.rule_clock_mhz ?? 0))))
  const labelW = 132, valW = 300
  const barW = Math.max(120, w - labelW - valW - 28)
  const groups = domainGroups(ips)
  const pacers = otfPacers(ips)
  const rule = pct0(margin)
  return (
    <div ref={ref} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {groups.map((g, gi) => (
        <div key={g.domain} className="dom-group" style={{ background: DOMAIN_TINT[gi % DOMAIN_TINT.length], borderLeftColor: DOMAIN_EDGE[gi % DOMAIN_EDGE.length] }}>
          <div className="dom-head">
            <b>{g.domain}</b>
            {dvfsApplied && g.level !== null && <span className="badge">domain Lv{g.level} · {fmt(g.voltage, 0)} mV</span>}
            <span className="faint">IP {g.rows.length}개 · level 결정 = <b>{g.driver.node.toUpperCase()}</b> (최고 요구 {fmt(g.driver.own_required_mhz ?? g.driver.required_clock_mhz, 0)} MHz{g.driver.basis ? ` · ${basisLabel(g.driver.basis)}` : ''})</span>
          </div>
          {g.rows.map((ip) => {
            const up = ip.rule_clock_mhz !== null && ip.set_clock_mhz > ip.rule_clock_mhz + 0.5
            const isDriver = ip.node === g.driver.node && g.rows.length > 1
            return (
              <div key={ip.node} style={{ display: 'flex', alignItems: 'center', gap: 8 }}
                {...tip({ title: `${ip.node.toUpperCase()} · ${g.domain}`, color: STAGE_COLOR[ip.stage], head: { label: 'set clock', value: `${fmt(ip.set_clock_mhz, 0)} MHz`, tone: 'strong' },
                  rows: [
                    { k: `${rule} rule clock`, v: ip.rule_clock_mhz === null ? '—' : `${fmt(ip.rule_clock_mhz, 0)} MHz` },
                    { k: '자체 필요 clock', v: `${fmt(ip.own_required_mhz ?? ip.required_clock_mhz, 1)} MHz` },
                    ...(ip.basis ? [{ k: '결정 요인', v: basisLabel(ip.basis) }] : []),
                    ...(ip.set_reason ? [{ k: 'set이 더 높은 이유', v: `${SET_REASON_LABEL[ip.set_reason] ?? ip.set_reason}${ip.domain_leader ? ` (${ip.domain_leader.toUpperCase()})` : ''}` }] : []),
                    ...(ip.sensor_readout_ms ? [{ k: 'sensor readout', v: `${fmt(ip.sensor_readout_ms, 2)} ms (HW 시간 하한)` }] : []),
                    ...(ip.rule_clock_mhz ? [{ k: 'rule 대비', v: `×${fmt(ip.set_clock_mhz / ip.rule_clock_mhz, 2)}`, tone: (up ? 'bad' : 'good') as 'bad' | 'good' }] : []),
                    { k: 'DVFS level · 전압', v: dvfsApplied && ip.dvfs_table !== false ? `Lv${ip.dvfs_level ?? '—'} · ${fmt(ip.voltage_mv, 0)} mV` : '표 없음' },
                    { k: 'HW 시간', v: ip.hw_ms === null ? '—' : `${fmt(ip.hw_ms, 2)} ms${ip.standalone_hw_ms ? ` (단독 ${fmt(ip.standalone_hw_ms, 2)})` : ''}` },
                    ...(ip.otf_group ? [{ k: `OTF 연동 ${ip.otf_group}`, v: ip.standalone_hw_ms
                      ? `${(pacers.get(ip.otf_group) ?? []).join(', ').toUpperCase()} 속도에 맞춰 대기`
                      : ip.sensor_readout_ms ? 'sensor readout에 맞춰 진행' : '그룹 시간 결정 (가장 느림)' }] : []),
                    { k: 'IP power', v: `${fmt(ip.power_mw, 1)} mW` },
                  ], foot: ip.clock_reason ?? undefined })}>
                <div style={{ width: labelW, flexShrink: 0, display: 'flex', gap: 6, alignItems: 'baseline' }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: STAGE_COLOR[ip.stage], flexShrink: 0 }} />
                  <b style={{ fontSize: 12 }}>{ip.node.toUpperCase()}</b>
                  <span className="faint" style={{ fontSize: 11 }}>{ip.stage.toUpperCase()}{ip.cores > 1 ? ` ×${ip.cores}` : ''}{ip.shared_streams > 1 ? ` ⇄${ip.shared_streams}` : ''}{isDriver ? ' ★' : ''}{ip.otf_group ? <span title={`OTF ${ip.otf_group}: domain이 달라도 같은 pixel rate로 연동`}> ⛓{ip.otf_group.replace('otf-', '')}</span> : null}</span>
                </div>
                <svg width={barW} height={20} style={{ flexShrink: 0 }} role="img" aria-label={`${ip.node} clock`}>
                  <rect x={0} y={1} width={barW} height={18} fill="rgba(255,255,255,0.7)" />
                  {ip.rule_clock_mhz !== null && <rect x={0} y={2} width={(ip.rule_clock_mhz / max) * barW} height={7} fill="#CFC7BA" />}
                  <rect x={0} y={11} width={(ip.set_clock_mhz / max) * barW} height={7} fill={up ? '#C2410C' : '#2F6F68'} />
                  {(ip.own_required_mhz ?? ip.required_clock_mhz) < ip.set_clock_mhz - 0.5 && <line x1={((ip.own_required_mhz ?? ip.required_clock_mhz) / max) * barW} x2={((ip.own_required_mhz ?? ip.required_clock_mhz) / max) * barW} y1={9} y2={20} stroke="#1F2430" strokeWidth={1.5} />}
                </svg>
                <span className="mono" style={{ width: valW, flexShrink: 0, fontSize: 12, color: up ? '#C2410C' : 'var(--text-2)' }}>
                  {dvfsApplied ? clockText(ip) : `${fmt(ip.rule_clock_mhz, 0)} → ${fmt(ip.set_clock_mhz, 0)} MHz`}{dvfsApplied && ip.dvfs_table !== false ? <span className="faint"> · {fmt(ip.voltage_mv, 0)} mV</span> : null}{ip.basis ? <span className="faint" title={ip.set_reason ? SET_REASON_LABEL[ip.set_reason] : undefined}> · {basisLabel(ip.basis)}</span> : null}
                </span>
              </div>
            )
          })}
        </div>
      ))}
      <div className="legend-row" style={{ paddingLeft: labelW + 8 }}>
        <Legend color="#CFC7BA" label={`${rule} rule`} /><Legend color="#2F6F68" label="Timing budget" /><Legend color="#C2410C" label="rule 대비 상승" />
        <span className="legend-item"><span style={{ width: 2, height: 10, background: '#1F2430' }} />자체 필요 clock (DVFS level·domain 공유 전)</span>
        <span className="faint" style={{ fontSize: 11 }}>배경색 = DVFS domain · ★ = domain level 결정 IP · ⛓n = OTF 연동 그룹 (domain이 달라도 같은 속도 · 시간 = 가장 느린 IP) · ×2 = MFC+MFD 병렬 · ⇄2 = 2 stream 공유</span>
        {!dvfsApplied && <span className="badge v-warn" title="DB에 이 SoC의 DVFS table이 없어 level·전압을 정할 수 없습니다 (clock은 필요값 그대로, 전압 기본값)">DVFS table 미연결 — level 없음</span>}
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
    { key: 'CPU', v: p.cpu_mw, c: SW_COLOR },
    { key: 'HW IP core', v: p.hw_mw, c: STAGE_COLOR.rt },
    { key: 'BW (MIF)', v: p.bw_mw, c: STAGE_COLOR.nrt },
  ]
  const ipRows = Object.entries(p.hw_by_ip).filter(([, v]) => v > 0)
  const cpuRows = Object.entries(p.cpu_by_task).filter(([, v]) => v > 0)
  const bwRows = [...Object.entries(bw.hw_by_ip).map(([k, v]) => ({ k, v, sw: false })), ...Object.entries(bw.sw_by_task).map(([k, v]) => ({ k, v, sw: true }))].sort((a, b) => b.v - a.v)
  const bwMax = niceMax(Math.max(1, ...bwRows.map((r) => r.v)))
  const pMax = niceMax(Math.max(1, ...ipRows.map(([, v]) => v), ...cpuRows.map(([, v]) => v)))
  const pct = (v: number, t: number) => (t > 0 ? `${fmt((v / t) * 100, 1)}%` : '—')
  return (
    <div ref={ref} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="faint" style={{ fontSize: 12 }}>Power (mW · Total 대비 비중)</div>
      <div className="tb-tiles">
        <Tile label="Total power" value={`${fmt(p.total_mw)} mW`} note="CPU + HW IP core + BW(MIF)" strong />
        <Tile label="CPU power" value={`${fmt(p.cpu_mw)} mW`} share={pct(p.cpu_mw, p.total_mw)} note={cpuTileNote(p)} color={SW_COLOR} />
        <Tile label="HW IP core power" value={`${fmt(p.hw_mw)} mW`} share={pct(p.hw_mw, p.total_mw)} note={p.zero_power_ips.length ? `unit_power=0: ${p.zero_power_ips.join(', ')}` : '전 IP 계수 있음'} color={STAGE_COLOR.rt} />
        <Tile label="BW (MIF) power" value={`${fmt(p.bw_mw)} mW`} share={pct(p.bw_mw, p.total_mw)} note={`HW ${fmt(p.bw_hw_mw, 0)} · CPU ${fmt(p.bw_sw_mw, 0)} mW`} color={STAGE_COLOR.nrt} />
      </div>
      <div className="faint" style={{ fontSize: 12 }}>BW (MB/s · Total 대비 비중)</div>
      <div className="tb-tiles">
        <Tile label="Total BW" value={`${fmt(bw.total_mbs, 0)} MB/s`} note={`${fmt(bw.total_mbs / 1000, 2)} GB/s · DMA W+R`} strong />
        <Tile label="CPU BW" value={`${fmt(bw.sw_mbs, 0)} MB/s`} share={pct(bw.sw_mbs, bw.total_mbs)} note={`memory_io 선언 task만: ${Object.keys(bw.sw_by_task).join(', ') || '없음'} · EIS·3A·RTA DRAM 접근 미모델`} color={SW_COLOR} />
        <Tile label="HW IP core BW" value={`${fmt(bw.hw_mbs, 0)} MB/s`} share={pct(bw.hw_mbs, bw.total_mbs)} note="IP DMA (RDMA + WDMA)" color={STAGE_COLOR.nrt} />
      </div>
      <div>
        <div className="faint" style={{ fontSize: 12, marginBottom: 4 }}>전력 구성 (mW, 비중)</div>
        <svg width={barW} height={26} role="img" aria-label="전력 구성">
          {(() => { let x = 0; return parts.map((s) => { const wpx = (s.v / Math.max(p.total_mw, 1e-9)) * barW; const g = (
            <g key={s.key}><title>{`${s.key} ${fmt(s.v)} mW`}</title><rect x={x} y={0} width={Math.max(0, wpx)} height={26} fill={s.c} stroke="#FFFFFF" />
              {wpx > 90 && <text x={x + wpx / 2} y={17} textAnchor="middle" fontSize={11} fill="#FFFFFF">{s.key} {fmt(s.v, 0)} ({fmt((s.v / p.total_mw) * 100, 0)}%)</text>}</g>); x += wpx; return g }) })()}
        </svg>
      </div>
      <div>
        <div className="faint" style={{ fontSize: 12, marginBottom: 4 }}>BW 구성 (MB/s, 비중)</div>
        <svg width={barW} height={26} role="img" aria-label="BW 구성">
          {(() => { let x = 0; return [{ key: 'HW IP core', v: bw.hw_mbs, c: STAGE_COLOR.nrt }, { key: 'CPU', v: bw.sw_mbs, c: SW_COLOR }].map((s) => { const wpx = (s.v / Math.max(bw.total_mbs, 1e-9)) * barW; const g = (
            <g key={s.key}><title>{`${s.key} ${fmt(s.v, 0)} MB/s`}</title><rect x={x} y={0} width={Math.max(0, wpx)} height={26} fill={s.c} stroke="#FFFFFF" />
              {wpx > 90 && <text x={x + wpx / 2} y={17} textAnchor="middle" fontSize={11} fill="#FFFFFF">{s.key} {fmt(s.v, 0)} ({fmt((s.v / bw.total_mbs) * 100, 0)}%)</text>}</g>); x += wpx; return g }) })()}
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

function Tile({ label, value, note, share, color, strong }: { label: string; value: string; note: string; share?: string; color?: string; strong?: boolean }) {
  return (
    <div className="tb-tile" style={{ borderLeft: color ? `4px solid ${color}` : undefined, background: strong ? 'var(--surface)' : undefined }}>
      <div className="faint" style={{ fontSize: 11 }}>{label}</div>
      <div><span className="mono" style={{ fontSize: 17, fontWeight: 600 }}>{value}</span>{share && <span className="badge" style={{ marginLeft: 6 }}>{share}</span>}</div>
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
  const tip = useTip()
  const rows = report.timeline
  const end = Math.max(1, ...rows.map((r) => r.end_ms))
  const labelW = 110
  const P = report.period_ms
  // ≥ 46 px per frame period; wider timelines scroll horizontally instead of squeezing
  const plotW = Math.max(300, w - labelW - 8, Math.ceil(end / P) * 46)
  const k = plotW / end
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
  const every = Math.max(1, Math.ceil(52 / (P * k)))  // label density
  // Output lanes get an extra strip for frame-to-frame interval marks (end → end of consecutive frames).
  const OUT = new Set(['dpu', 'enc'])
  const tol = Math.max(0.01, P * (report.intervals.tolerance || 0.001))
  const laneH = (id: string) => (OUT.has(id) ? 38 : 24)
  const laneY: number[] = []
  let acc = 16
  for (const l of lanes) { laneY.push(acc); acc += laneH(l.id) }
  const H = acc + 6
  return (
    <div ref={ref} style={{ overflowX: 'auto' }}>
      <svg width={labelW + plotW} height={H} role="img" aria-label="pipeline timeline">
        {ticks.map((t, i) => i % 2 === 1 && <rect key={`b${i}`} x={labelW + t * k} y={14} width={Math.min(P, end - t) * k} height={H - 18} fill="#F7F4EE" />)}
        {ticks.map((t, i) => <g key={i}><line x1={labelW + t * k} x2={labelW + t * k} y1={12} y2={H - 4} stroke="#7A7062" strokeDasharray="4 3" strokeWidth={1} opacity={0.7} />
          {i % every === 0 && <text x={labelW + t * k + 2} y={10} fontSize={10} fill="#5B5346" fontFamily="var(--mono)">{fmt(t, t < 100 ? 1 : 0)}ms</text>}</g>)}
        {lanes.map((l, li) => {
          const outs = OUT.has(l.id) ? [...l.bars].sort((a, b) => a.end_ms - b.end_ms) : []
          return (
          <g key={l.id} transform={`translate(0, ${laneY[li]})`}>
            <text x={labelW - 6} y={14} textAnchor="end" fontSize={11} fill="#3B3F4A">{l.name}</text>
            <rect x={labelW} y={1} width={plotW} height={20} fill="#FBFAF7" />
            {l.bars.map((b, i) => {
              const color = l.id.includes('sw') ? SW_COLOR : STAGE_COLOR[b.stage]
              const bw = Math.max(1.5, (b.end_ms - b.start_ms) * k)
              return (
                <g key={i} {...tip({ title: `${b.node.toUpperCase()} · f${b.frame}`, color, head: { label: '소요', value: `${fmt(b.end_ms - b.start_ms, 2)} ms`, tone: 'strong' },
                  rows: [{ k: 'frame 경계 기준 시작', v: `+${fmt(b.start_ms - b.frame * P, 2)} ms (f${b.frame} 경계)` }, { k: '주기 대비', v: `${fmt(((b.end_ms - b.start_ms) / P) * 100, 0)}% of ${fmt(P, 2)} ms` },
                    { k: '절대 시각', v: `${fmt(b.start_ms, 2)} → ${fmt(b.end_ms, 2)} ms`, tone: 'muted' }] })}>
                  <rect x={labelW + b.start_ms * k} y={3} width={bw} height={16} fill={color} opacity={b.frame % 2 ? 0.62 : 1} rx={2} />
                  {bw > 22 && <text x={labelW + b.start_ms * k + bw / 2} y={15} textAnchor="middle" fontSize={10} fill="#FFFFFF">f{b.frame}</text>}
                </g>
              )
            })}
            {outs.slice(1).map((b, i) => {
              const a = outs[i], dt = b.end_ms - a.end_ms, x1 = labelW + a.end_ms * k, x2 = labelW + b.end_ms * k
              const bad = Math.abs(dt - P) > tol
              const c = bad ? '#B42318' : '#5B6B73'
              return <g key={`iv${i}`} {...tip({ title: `${l.name} f${a.frame} → f${b.frame} 출력 간격`, color: c, head: { label: '간격', value: `${fmt(dt, 3)} ms`, tone: bad ? 'bad' : 'good' },
                rows: [{ k: '목표', v: `${fmt(P, 3)} ms` }, { k: '차이', v: `${dt - P >= 0 ? '+' : ''}${fmt(dt - P, 3)} ms`, tone: bad ? 'bad' : 'muted' }] })}>
                <rect x={x1} y={22} width={Math.max(2, x2 - x1)} height={16} fill="transparent" />
                <line x1={x1} x2={x2} y1={28} y2={28} stroke={c} strokeWidth={1} />
                <line x1={x1} x2={x1} y1={24} y2={32} stroke={c} /><line x1={x2} x2={x2} y1={24} y2={32} stroke={c} />
                {x2 - x1 > 34 && <text x={(x1 + x2) / 2} y={36} textAnchor="middle" fontSize={9.5} fill={c} fontFamily="var(--mono)">{fmt(dt, 2)}</text>}
              </g>
            })}
          </g>
        )})}
      </svg>
      <div className="faint" style={{ fontSize: 11 }}>세로 점선 = frame 경계 {fmt(P, 2)} ms ({fmt(report.fps, 0)} fps) · 음영 = 홀수 frame 구간 · DPU(preview) · MFC(video) 아래 눈금 = 연속 frame 출력 완료 간격(ms, end→end) · 빨강 = 목표 {fmt(P, 2)} ms ±{fmt((report.intervals.tolerance || 0) * 100, 1)}% 이탈</div>
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
              {x.s.jitter_ms !== undefined && <span className="mono faint" style={{ fontSize: 11.5 }} title="σ = 판정 구간 간격의 표준편차 · p95 = |간격 − 주기|의 95%ile · drop = 주기의 ~k배 간격이면 k−1 frame 누락 · warm-up = 첫 정상 간격 전 이탈 개수">
                σ {fmt(x.s.jitter_ms ?? null, 3)} · p95 {fmt(x.s.p95_dev_ms ?? null, 3)} ms · drop {x.s.drops ?? 0}{(x.s.drops ?? 0) > 0 ? ' ⚠' : ''} · warm-up {x.s.warmup_observed ?? 0}{x.s.warmup_excluded ? ` (앞 ${x.s.warmup_excluded}개 판정 제외)` : ''}</span>}
              <span className="grow" />
              <span className="mono" style={{ fontSize: 12 }}>latency {fmt(x.lat, 1)} ms ({fmt(x.lf, 2)} frame)</span>
            </div>
            <svg width={plotW} height={H} role="img" aria-label={`${x.key} interval`}>
              <rect x={0} y={0} width={plotW} height={H} fill="#FBFAF7" />
              <rect x={0} y={y(t * (1 + tol))} width={plotW} height={Math.max(1, y(t * (1 - tol)) - y(t * (1 + tol)))} fill="#E3EEEB" />
              <line x1={0} x2={plotW} y1={y(t)} y2={y(t)} stroke="#2F6F68" strokeDasharray="4 3" />
              <text x={plotW - 4} y={y(t) - 4} textAnchor="end" fontSize={10} fill="#2F6F68">target {fmt(t, 3)} ms</text>
              {x.s.values.map((v, i) => {
                const bad = Math.abs(v - t) > t * tol && i >= (x.s.warmup_excluded ?? 0)
                return <circle key={i} cx={16 + (i * (plotW - 32)) / Math.max(1, n - 1)} cy={Math.max(5, Math.min(H - 5, y(v)))} r={4.5} fill={bad ? '#7F1D1D' : i < (x.s.warmup_excluded ?? 0) ? '#B8B2A7' : x.c}><title>{`f${i + 1}: ${fmt(v, 3)} ms`}</title></circle>
              })}
            </svg>
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------- ④ what-if
export function WhatIf({ rows, current, margin = 0.25 }: { rows: WhatIfRow[]; current: { statistic: string; eis: boolean; scale: number }; margin?: number }) {
  const [ref, w] = useWidth<HTMLDivElement>(600)
  // one DVFS domain at a time: NRT spans several (CAM / INTCAM) and their clocks must not share one line
  const domains = useMemo(() => whatIfDomains(rows), [rows])
  const [pick, setPick] = useState<string>('')
  const domain = domains.includes(pick) ? pick : domains[0] ?? ''
  const clockOf = (r: WhatIfRow) => (domain ? domainOf(r, domain)?.set_mhz ?? null : r.nrt_clock_mhz)
  const plotW = Math.max(260, w - 60), H = 220
  const scales = [...new Set(rows.map((r) => r.scale))].sort((a, b) => a - b)
  const vals = rows.map((r) => clockOf(r) ?? 0)
  const rule = (domain ? rows.map((r) => domainOf(r, domain)?.rule_mhz).find((v) => v) : rows.find((r) => r.nrt_rule_clock_mhz)?.nrt_rule_clock_mhz) ?? 0
  const max = niceMax(Math.max(rule, ...vals))
  const x = (s: number) => 50 + ((s - scales[0]) / Math.max(1e-9, scales[scales.length - 1] - scales[0])) * (plotW - 10)
  const y = (v: number) => H - 24 - (v / max) * (H - 40)
  const lines = [
    { stat: 'max', eis: true, c: '#C2410C', dash: '' }, { stat: 'max', eis: false, c: '#C2410C', dash: '6 4' },
    { stat: 'mean', eis: true, c: '#2F6F68', dash: '' }, { stat: 'mean', eis: false, c: '#2F6F68', dash: '6 4' },
  ]
  const cur = rows.find((r) => r.statistic === current.statistic && r.eis === current.eis && Math.abs(r.scale - current.scale) < 1e-6)
  const curD = cur && domain ? domainOf(cur, domain) : undefined
  const be = domain ? breakEven(rows, domain, current.statistic, current.eis) : null
  return (
    <div ref={ref}>
      {domains.length > 1 && <div className="toolbar" style={{ gap: 8, marginBottom: 4, fontSize: 12 }}>
        <span className="faint">DVFS domain</span>
        <div className="seg sm" role="radiogroup" aria-label="what-if DVFS domain">
          {domains.map((d) => <button key={d} type="button" role="radio" aria-checked={d === domain} className={d === domain ? 'on' : ''} onClick={() => setPick(d)}>{d}</button>)}
        </div>
        <span className="faint">IP: {[...new Set(rows.map((r) => domainOf(r, domain)?.ip).filter(Boolean))].join(', ').toUpperCase()}</span>
      </div>}
      <svg width={plotW + 60} height={H} role="img" aria-label="SW 증가 대비 NRT clock">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => <g key={f}><line x1={50} x2={plotW + 40} y1={y(max * f)} y2={y(max * f)} stroke="#EFEAE2" /><text x={44} y={y(max * f) + 3} textAnchor="end" fontSize={10} fill="#8A8274">{fmt(max * f, 0)}</text></g>)}
        {scales.map((s) => <text key={s} x={x(s)} y={H - 6} textAnchor="middle" fontSize={10} fill="#8A8274">×{s.toFixed(1)}</text>)}
        {rule > 0 && <><line x1={50} x2={plotW + 40} y1={y(rule)} y2={y(rule)} stroke="#7A4B12" strokeDasharray="5 4" /><text x={plotW + 40} y={y(rule) - 4} textAnchor="end" fontSize={10} fill="#7A4B12">{domain ? `${domain} ` : ''}{pct0(margin)} rule {fmt(rule, 0)} MHz</text></>}
        {be && <><line x1={x(be.scale)} x2={x(be.scale)} y1={16} y2={H - 24} stroke="#7F1D1D" strokeDasharray="2 3" /><text x={x(be.scale) > (plotW + 60) * 0.6 ? x(be.scale) - 4 : x(be.scale) + 4} textAnchor={x(be.scale) > (plotW + 60) * 0.6 ? 'end' : 'start'} y={24} fontSize={10} fill="#7F1D1D">×{be.scale.toFixed(1)}부터 {fmt(be.from, 0)}→{fmt(be.to, 0)} MHz</text></>}
        {lines.map((l) => {
          const pts = rows.filter((r) => r.statistic === l.stat && r.eis === l.eis && clockOf(r) !== null).sort((a, b) => a.scale - b.scale)
          return <g key={`${l.stat}${l.eis}`}>
            <polyline points={pts.map((r) => `${x(r.scale)},${y(clockOf(r) ?? 0)}`).join(' ')} fill="none" stroke={l.c} strokeWidth={2.2} strokeDasharray={l.dash} />
            {pts.filter((r) => r.verdict.status === 'fail').map((r) => <circle key={r.scale} cx={x(r.scale)} cy={y(clockOf(r) ?? 0)} r={4} fill="#7F1D1D"><title>{`fail: ${r.verdict.reasons[0] ?? ''}`}</title></circle>)}
          </g>
        })}
        {cur && <circle cx={x(cur.scale)} cy={y(clockOf(cur) ?? 0)} r={6} fill="#1F2430" stroke="#FFFFFF" strokeWidth={2} />}
      </svg>
      <div className="legend-row">
        <span className="legend-item"><span style={{ width: 18, borderTop: '3px solid #C2410C' }} />max · EIS on</span>
        <span className="legend-item"><span style={{ width: 18, borderTop: '2px dashed #C2410C' }} />max · EIS off</span>
        <span className="legend-item"><span style={{ width: 18, borderTop: '3px solid #2F6F68' }} />mean · EIS on</span>
        <span className="legend-item"><span style={{ width: 18, borderTop: '2px dashed #2F6F68' }} />mean · EIS off</span>
        <span className="legend-item"><span style={{ width: 8, height: 8, borderRadius: 4, background: '#7F1D1D' }} />fail</span>
        <span className="legend-item faint">계단 = DVFS level (필요 clock이 level을 조금만 넘어도 다음 level)</span>
      </div>
      {cur && <div className="mono" style={{ fontSize: 12, marginTop: 4 }}>현재 {current.statistic} · EIS {current.eis ? 'on' : 'off'} · ×{current.scale.toFixed(1)} → {curD
        ? `${curD.domain} 필요 ${fmt(curD.required_mhz, 1)} → ${fmt(curD.set_mhz, 0)} MHz${curD.level !== null ? ` (L${curD.level})` : ''} · ${curD.ip.toUpperCase()}`
        : `${cur.nrt_driver?.toUpperCase()} ${fmt(cur.nrt_clock_mhz, 0)} MHz`} · NRT SW {fmt(cur.stages.nrt.sw_ms, 1)} ms · HW 예산 {fmt(cur.stages.nrt.budget_ms, 1)} ms · {cur.interval_ok ? '간격 OK' : '간격 ✗'}</div>}
    </div>
  )
}

// ---------------------------------------------------------------- fleet ranking
/** Ranked dumbbell: one row per variant (rule clock → required clock), sorted by factor. Never overlaps. */
export function FleetRank({ rows, onPick, limit, margin = 0.25 }: { rows: FleetRow[]; onPick: (v: string) => void; limit: number; margin?: number }) {
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
        <span style={{ width: labelW }}>Variant</span><span style={{ width: plotW }}>NRT 필요 clock (MHz) · ○ {pct0(margin)} rule → ● timing budget</span>
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
            <span className="mono" style={{ width: valW, textAlign: 'left', color }}>×{fmt(rule ? set / rule : null, 2)} · {r.clocks.nrt.domain ? `${r.clocks.nrt.domain} ` : ''}{fmt(set, 0)} MHz{r.clocks.nrt.level !== null ? ` L${r.clocks.nrt.level}` : ''}</span>
          </button>
        )
      })}
      <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>axis 0–{fmt(max, 0)} MHz · 정렬 = 배율 내림차순 · 행 클릭 = variant 상세</div>
    </div>
  )
}
