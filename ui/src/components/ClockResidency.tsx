// Clock-domain residency views (CPU cluster · DSU · GPU): calibration detail card, scenario comparison,
// and the compact distribution used by the CPU what-if "모델 확인" card.
import { Fragment, useState, type ReactNode } from 'react'
import { useAsync } from '../lib/route'
import { clockApi, freqColor, groupLabel, mhzText, oppColor, pctText, pickStats, type Basis, type ClockView, type ResBin } from '../lib/clockResidency'
import { Card } from './TimingCharts'

/** Time share stacked by frequency (colour = fraction of fmax: light low → dark near fmax). */
export function ResidencyStrip({ bins, fmax, width = 220, height = 12 }: { bins: ResBin[]; fmax?: number | null; width?: number; height?: number }) {
  let x = 0
  return (
    <svg width={width} height={height} role="img" aria-label={bins.map((b) => `${mhzText(b.mhz)} ${pctText(b.ratio)}`).join(', ')}>
      <rect width={width} height={height} fill="#EFEAE1" rx={2} />
      {bins.map((b, i) => {
        const w = width * b.ratio
        const el = <rect key={b.mhz} x={x} y={0} width={Math.max(0, w)} height={height} fill={freqColor(b.mhz, fmax, i, bins.length)}><title>{`${mhzText(b.mhz)} · ${pctText(b.ratio, 1)}`}</title></rect>
        x += w
        return el
      })}
    </svg>
  )
}

export interface Mark { mhz: number; label: string; color: string; dash?: boolean }

/** Frequency axis (0 … fmax): bars = time share per frequency, 전체(grey) vs running(teal); marks = vertical lines. */
export function ResidencyHist({ wall, active, fmax, marks = [], width = 360, height = 92, compact = false }: {
  wall?: ResBin[] | null; active?: ResBin[] | null; fmax?: number | null; marks?: Mark[]; width?: number; height?: number; compact?: boolean
}) {
  const freqs = [...new Set([...(wall ?? []), ...(active ?? [])].map((b) => b.mhz))].sort((a, b) => a - b)
  const top = Math.max(fmax ?? 0, ...freqs, ...marks.map((m) => m.mhz), 1)
  const padL = compact ? 2 : 8, padR = compact ? 2 : 8, axisH = compact ? 0 : 16, labelH = compact ? 0 : 4
  const plotW = width - padL - padR, plotH = height - axisH - labelH
  const x = (f: number) => padL + (f / (top * 1.04)) * plotW
  const peak = Math.max(0.0001, ...[...(wall ?? []), ...(active ?? [])].map((b) => b.ratio))
  const bw = Math.max(3, Math.min(14, plotW / Math.max(1, freqs.length) / 3))
  const series: [ResBin[] | null | undefined, string, number][] = [[wall, '#C9C2B6', active?.length ? -bw / 2 : 0], [active, '#2F6F68', wall?.length ? bw / 2 : 0]]
  return (
    <svg width={width} height={height} role="img" aria-label="clock residency by frequency">
      {fmax ? <line x1={x(fmax)} x2={x(fmax)} y1={labelH} y2={labelH + plotH} stroke="#B9B1A4" strokeDasharray="2 3"><title>{`fmax ${mhzText(fmax)}`}</title></line> : null}
      {series.map(([bins, color, off]) => (bins ?? []).map((b) => {
        const h = (b.ratio / peak) * plotH
        return <rect key={`${color}${b.mhz}`} x={x(b.mhz) + off - bw / 2} y={labelH + plotH - h} width={bw} height={h} fill={color}>
          <title>{`${color === '#2F6F68' ? 'running' : '전체'} ${mhzText(b.mhz)} · ${pctText(b.ratio, 1)}`}</title></rect>
      }))}
      {marks.map((m) => <line key={m.label} x1={x(m.mhz)} x2={x(m.mhz)} y1={labelH - (compact ? 0 : 2)} y2={labelH + plotH} stroke={m.color} strokeWidth={1.5}
        strokeDasharray={m.dash ? '4 3' : undefined}><title>{`${m.label} ${mhzText(m.mhz)}`}</title></line>)}
      <line x1={padL} x2={width - padR} y1={labelH + plotH} y2={labelH + plotH} stroke="#B9B1A4" />
      {!compact && freqs.map((f, i) => (i === 0 || i === freqs.length - 1 || freqs.length <= 6) &&
        <text key={f} x={x(f)} y={height - 3} fontSize={10} textAnchor="middle" fill="#7A7468">{f >= 1000 ? `${(f / 1000).toFixed(1)}G` : f}</text>)}
    </svg>
  )
}

const NOTE_BADGE = { warn: 'v-warn', info: '' } as const
const fmt0 = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v).toLocaleString()}`)

export const CLOCK_HELP: ReactNode = <>
  <b>측정 중 각 clock domain이 어떤 주파수에 얼마나 머물렀는지</b> (perfetto cpufreq · cpuidle · GPU freq track, PMU pass별 export).
  <ul>
    <li><b>running 기준</b> — idle(WFI·power down)을 뺀 동작 시간 중 주파수 비율. 실제 cycle이 실행된 주파수라 <b>dynamic power</b>는 이 분포로 계산합니다 (cycle 가중). 없으면 전체 기준으로 근사.</li>
    <li><b>전체 기준</b> — capture 전체 시간 중 governor 주파수 비율. 전압이 정해지므로 <b>leakage</b>는 이 분포를 씁니다.</li>
    <li><b>고 OPP</b> — topology(CPU) / IP catalog(GPU)의 최대 OPP의 80% 이상 구간 비율. 최대 OPP를 모르면 표시하지 않습니다.</li>
    <li><b>pass JSD</b> — 15초 × 3 PMU pass 사이 분포 차이 (0 = 같음, 0.05 초과 = 측정 중 온도·부하 변화 의심 → capture 품질 확인).</li>
    <li>메모는 보고서 ④ 실측 대조의 “Clock 분포 실측”과 같은 규칙으로 생성됩니다.</li>
  </ul>
</>

/** Calibration detail: per-domain distribution, KPIs and reading notes; row click = 전체 vs running histogram. */
export function ClockResidencyCard({ view, cpuLink }: { view: ClockView; cpuLink?: string }) {
  const [basis, setBasis] = useState<Basis>('active')
  const [open, setOpen] = useState<string | null>(null)
  const warns = view.domains.reduce((a, d) => a + d.notes.filter((n) => n.level === 'warn').length, 0)
  const hasPower = view.domains.some((d) => d.power)
  const cols = hasPower ? 9 : 8
  const anyActive = view.domains.some((d) => d.active)
  return (
    <Card id="cal-clock" title="Clock 분포 — CPU · DSU · GPU" help={CLOCK_HELP} defaultWide
      note={<>막대 = 주파수별 시간 비율 · 색 = fmax 대비 (진할수록 fmax 근처) · 행 클릭 = 전체 vs running 비교{warns ? <> · <span className="badge v-warn">확인 {warns}</span></> : null}</>}
      actions={anyActive ? <div className="seg sm" role="group" aria-label="기준">
        <button className={basis === 'active' ? 'on' : ''} onClick={() => setBasis('active')} title="idle을 뺀 동작 시간 기준">running 기준</button>
        <button className={basis === 'wall' ? 'on' : ''} onClick={() => setBasis('wall')} title="capture 전체 시간 기준">전체 기준</button>
      </div> : undefined}>
      {view.summary.length > 0 && <ul className="clk-summary">{view.summary.map((s) => <li key={s}>{s}</li>)}</ul>}
      <div className="table-x">
        <table className="tb-mini-table clk-table" style={{ width: '100%' }}>
          <thead><tr><th>Domain</th><th>분포</th><th style={{ textAlign: 'right' }}>평균</th><th style={{ textAlign: 'right' }}>최빈</th>
            <th style={{ textAlign: 'right' }} title="최대 OPP의 80% 이상">고 OPP</th><th style={{ textAlign: 'right' }} title="동작(running) 시간 비율">동작</th>
            <th style={{ textAlign: 'right' }} title="PMU pass 사이 분포 차이">pass JSD</th>
            {hasPower && <th style={{ textAlign: 'right' }} title="IP catalog power_model × 분포 (CPU는 CPU what-if)">추정 mW</th>}<th>메모</th></tr></thead>
          <tbody>{view.domains.map((d, i) => {
            const { s, used } = pickStats(d, basis)
            const key = `${d.domain_class}/${d.domain}`
            const prev = view.domains[i - 1]
            return <Fragment key={key}>
              {(!prev || groupLabel(prev) !== groupLabel(d)) && <tr className="clk-group"><td colSpan={cols}>{groupLabel(d)}</td></tr>}
              <tr className={`clickable ${open === key ? 'selected' : ''}`} onClick={() => setOpen(open === key ? null : key)} aria-expanded={open === key}>
                <td className="mono"><b>{d.domain}</b>{used !== basis && <span className="faint" title="선택한 기준의 분포가 없어 다른 기준 표시"> ({used === 'wall' ? '전체' : 'running'})</span>}</td>
                <td>{s ? <><ResidencyStrip bins={s.bins} fmax={d.opp_max_mhz} /><div className="faint" style={{ fontSize: 11 }}>{mhzText(s.min_mhz)} … {mhzText(s.max_mhz)}{d.opp_max_mhz ? ` / fmax ${mhzText(d.opp_max_mhz)}` : ''}</div></> : '—'}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{mhzText(s?.mean_mhz)}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{mhzText(s?.dominant_mhz)} <span className="faint">{pctText(s?.dominant_share)}</span></td>
                <td className="mono" style={{ textAlign: 'right' }}>{s?.high_share === null || s?.high_share === undefined ? <span className="faint" title="최대 OPP 미상">—</span>
                  : <span className={s.high_share >= view.thresholds.high_opp_warn ? 'badge v-warn' : ''}>{pctText(s.high_share)}</span>}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{pctText(d.active_ratio)}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{d.pass_jsd === null ? <span className="faint">—</span>
                  : <span className={d.pass_jsd > view.thresholds.pass_jsd_warn ? 'badge v-warn' : ''}>{d.pass_jsd.toFixed(3)}</span>}</td>
                {hasPower && <td className="mono" style={{ textAlign: 'right' }} title={d.power ? [...d.power.notes, d.power.measured_mw !== null ? `실측 rail ${d.power.rails.join(', ')}` : ''].filter(Boolean).join('\n') : ''}>
                  {d.power ? <>{fmt0(d.power.total_mw)}{d.power.sample && <span className="badge v-warn" style={{ marginLeft: 4 }}>SAMPLE</span>}
                    {d.power.measured_mw !== null && <div className="faint" style={{ fontSize: 11 }}>실측 {fmt0(d.power.measured_mw)}{d.power.delta_pct !== null ? ` (${d.power.delta_pct >= 0 ? '+' : ''}${d.power.delta_pct.toFixed(0)}%)` : ''}</div>}</> : <span className="faint">—</span>}</td>}
                <td style={{ maxWidth: 420 }}>{d.notes.length ? d.notes.map((n) => <div key={n.code} className={`clk-note ${n.level}`}>
                  {n.level === 'warn' && <span className={`badge ${NOTE_BADGE[n.level]}`}>확인</span>} {n.text}</div>) : <span className="faint">—</span>}</td>
              </tr>
              {open === key && <tr className="clk-detail"><td colSpan={cols}>
                <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'flex-start' }}>
                  <ResidencyHist wall={d.wall?.bins} active={d.active?.bins} fmax={d.opp_max_mhz}
                    marks={[...(d.active ? [{ mhz: d.active.mean_mhz, label: 'running 평균', color: '#174D47' }] : []),
                            ...(d.wall ? [{ mhz: d.wall.mean_mhz, label: '전체 평균', color: '#8A8274', dash: true }] : [])]} width={420} height={110} />
                  <div style={{ fontSize: 12 }}>
                    <div className="legend-row"><span className="legend-item"><span style={{ width: 10, height: 10, background: '#C9C2B6' }} />전체</span>
                      <span className="legend-item"><span style={{ width: 10, height: 10, background: '#2F6F68' }} />running</span>
                      <span className="legend-item"><span style={{ width: 14, height: 0, borderTop: '2px solid #174D47' }} />running 평균</span>
                      <span className="legend-item"><span style={{ width: 14, height: 0, borderTop: '2px dashed #8A8274' }} />전체 평균</span>
                      {d.opp_max_mhz ? <span className="legend-item"><span style={{ width: 14, height: 0, borderTop: '1px dashed #B9B1A4' }} />fmax</span> : null}</div>
                    <table className="tb-mini-table" style={{ marginTop: 6 }}><tbody>
                      <tr><td>동작 · clock gated · power gated</td><td className="mono">{pctText(d.active_ratio)} · {pctText(d.clock_gated_ratio)} · {pctText(d.power_gated_ratio)}</td></tr>
                      <tr><td>평균 (running / 전체)</td><td className="mono">{mhzText(d.active?.mean_mhz)} / {mhzText(d.wall?.mean_mhz)}</td></tr>
                      <tr><td>중앙값 (running / 전체)</td><td className="mono">{mhzText(d.active?.p50_mhz)} / {mhzText(d.wall?.p50_mhz)}</td></tr>
                      <tr><td>source</td><td className="faint">{d.source === 'perfetto' ? 'perfetto digest (cpu_breakdown)' : 'metric observation'}</td></tr>
                      {d.power && <tr><td>추정 power (dynamic + static)</td><td className="mono">{fmt0(d.power.dynamic_mw)} + {fmt0(d.power.static_mw)} = {fmt0(d.power.total_mw)} mW <span className="faint">({d.power.ip_ref}, fmax 100% {fmt0(d.power.at_fmax_mw)} mW)</span></td></tr>}
                    </tbody></table>
                    {d.domain_class === 'cpu' && !d.is_dsu && cpuLink && <a className="btn" style={{ marginTop: 6 }} href={cpuLink}>CPU what-if에서 분산 검토 →</a>}
                  </div>
                </div>
              </td></tr>}
            </Fragment>
          })}</tbody>
        </table>
      </div>
    </Card>
  )
}

/** Scenario-level table: clock residency of every measurement (variant / SW version comparison). */
export function ClockCompareCard({ scenarioId, selectedId, onPick }: { scenarioId?: string; selectedId?: string; onPick: (id: string) => void }) {
  const rows = useAsync(() => clockApi.rows(scenarioId), [scenarioId])
  const data = rows.data ?? []
  if (rows.error) return <div className="err">{rows.error}</div>
  if (data.length < 1) return null
  const domains: { key: string; label: string; fmax: number | null }[] = []
  for (const r of data) for (const d of r.domains) {
    const key = `${d.domain_class}/${d.domain}`
    if (!domains.some((x) => x.key === key)) domains.push({ key, label: d.domain, fmax: d.opp_max_mhz })
  }
  const shade = (mean: number, fmax: number | null) => {
    const t = Math.max(0, Math.min(1, mean / (fmax ?? Math.max(...data.flatMap((r) => r.domains.map((d) => d.mean_mhz))))))
    return oppColor(Math.round(t * 9), 10)
  }
  return (
    <Card id="cal-clock-cmp" title="Clock 분포 비교 — 측정별" defaultWide minHeight={120}
      note="칸 = 평균 주파수 (running 기준, 없으면 전체) · 색이 진할수록 fmax에 가까움 · ⚠ = 확인 메모 · 행 클릭 = 상세">
      <div className="table-x">
        <table className="tb-mini-table" style={{ width: '100%' }}>
          <thead><tr><th>Variant</th><th>SW</th><th>측정</th>{domains.map((d) => <th key={d.key} style={{ textAlign: 'center' }}>{d.label}</th>)}</tr></thead>
          <tbody>{data.map((r) => (
            <tr key={r.id} className={`clickable ${r.id === selectedId ? 'selected' : ''}`} onClick={() => onPick(r.id)}>
              <td className="mono">{r.variant_id.replace('cam-rec-', '')}{r.synthetic && <span className="badge v-warn" style={{ marginLeft: 6 }}>합성</span>}</td>
              <td className="faint">{r.sw_baseline_ref ?? '—'}</td>
              <td className="mono faint">{r.measured_at?.slice(0, 10) ?? '—'}</td>
              {domains.map((k) => {
                const d = r.domains.find((x) => `${x.domain_class}/${x.domain}` === k.key)
                if (!d) return <td key={k.key} className="faint" style={{ textAlign: 'center' }}>—</td>
                if (d.active_ratio !== null && d.active_ratio < 0.005) return <td key={k.key} className="faint" style={{ textAlign: 'center' }} title="측정 중 거의 동작하지 않음">idle</td>
                const bg = shade(d.mean_mhz, d.opp_max_mhz)
                const dark = parseInt(bg.slice(1, 3), 16) < 0x80
                return <td key={k.key} className="mono" style={{ textAlign: 'center', background: bg, color: dark ? '#fff' : undefined }}
                  title={`${d.domain} ${d.basis === 'active' ? 'running' : '전체'} 평균 ${mhzText(d.mean_mhz)} · 동작 ${pctText(d.active_ratio)} · 고 OPP ${pctText(d.high_share)}${d.pass_jsd !== null ? ` · JSD ${d.pass_jsd.toFixed(3)}` : ''}`}>
                  {mhzText(d.mean_mhz)}{d.warns ? ' ⚠' : ''}</td>
              })}
            </tr>))}</tbody>
        </table>
      </div>
    </Card>
  )
}

/** Compact measured distribution + EAS model MHz for the CPU what-if "모델 확인" table. */
export function ModelCheckDist({ wall, active, modelMhz, fmax }: { wall?: ResBin[]; active?: ResBin[]; modelMhz?: number; fmax?: number }) {
  if (!wall?.length && !active?.length) return <span className="faint">—</span>
  const bins = active?.length ? active : wall!
  const mean = bins.reduce((a, b) => a + b.mhz * b.ratio, 0) / Math.max(1e-9, bins.reduce((a, b) => a + b.ratio, 0))
  return <ResidencyHist wall={wall} active={active} fmax={fmax} compact width={170} height={30}
    marks={[{ mhz: mean, label: active?.length ? 'running 평균' : '측정 평균', color: '#174D47' },
            ...(modelMhz ? [{ mhz: modelMhz, label: '모델 (EAS 재현)', color: '#B42318', dash: true }] : [])]} />
}
