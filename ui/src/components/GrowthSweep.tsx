// CPU what-if, result first (CPU-02..05): SW growth × cluster distribution.
// Tiles (tolerance, OPP step, spread vs concentrate), the growth curve with OPP / timing markers,
// the growth × strategy heatmap and the OPP state table.
import { useWidth } from './Charts'
import { useTip } from './ChartTip'
import { Card } from './TimingCharts'
import { fmt } from '../lib/timingBudget'
import { mhzClusters, spreadVsConcentrate, strategyMatrix, sweepStageTip, type GrowthSweep as Sweep, type SweepPoint } from '../lib/growthSweep'

const sg = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(d)}`)
const gx = (g: number) => `×${g.toFixed(g * 10 % 1 === 0 ? 1 : 2)}`

export function SweepTiles({ s, synthetic }: { s: Sweep; synthetic: boolean }) {
  const p0 = s.points[0], pN = s.points[s.points.length - 1]
  const lim = s.limits
  const svc = p0 ? spreadVsConcentrate(p0) : { spread: null, concentrate: null }
  const gain = p0?.best && p0.reference ? p0.best.total_mw - p0.reference.total_mw : null
  const mhz = (p?: SweepPoint) => (p?.reference ? mhzClusters(p).map((c) => `${c.replace(/^MID_/, '')} ${fmt(p.reference!.mhz[c], 0)}`).join(' / ') + ` · DSU ${fmt(p.reference.mhz.dsu, 0)}` : '')
  let first = true
  const tile = (label: string, value: string, note: string, cls = '') => {
    const badge = synthetic && first
    first = false
    return (
    <div key={label} className="panel tb-kpi"><div className="faint" style={{ fontSize: 12 }}>{label}{badge && <span className="badge v-warn" style={{ marginLeft: 6 }} title="합성 profile — 모델 동작 확인용, 실제 절감 근거 아님">합성 profile</span>}</div>
      <div className={`mono ${cls}`} style={{ fontSize: 20, fontWeight: 600 }}>{value}</div><div className="faint" style={{ fontSize: 11 }}>{note}</div></div>)
  }
  const step = lim.opp_step
  return (
    <section className="tb-kpis" aria-label="CPU what-if 결론">
      {tile(`현재 배치 · SW ${gx(p0.growth)}`, `${fmt(p0.reference?.total_mw, 1)} mW`, `CPU + DSU · ${mhz(p0)} MHz`)}
      {tile('최적 재배치 이득', gain === null ? '—' : `${sg(gain)} mW`, gain !== null && p0.reference ? `${sg((gain / p0.reference.total_mw) * 100)}% · 이동 ${p0.best?.moved.length ?? 0} task` : '조건 만족 배치 없음', (gain ?? 0) < -0.05 ? 'pm-down' : '')}
      {tile('SW 증가 허용치', lim.tolerance === null ? `> ${gx(pN.growth)}` : gx(lim.tolerance),
        [lim.timing_at !== null ? `timing 여유(RT chain 포함) 소진 ${gx(lim.timing_at)}` : 'Timing Budget 연동 없음', step ? `첫 OPP 계단 ${gx(step.growth_to)}` : '범위 안 OPP 계단 없음',
          ...((lim.opp_steps ?? []).length > 1 ? [`계단 ${(lim.opp_steps ?? []).length}개`] : [])].join(' · '),
        lim.tolerance !== null && lim.tolerance < pN.growth ? 'cal-t-warn' : '')}
      {tile(step ? `첫 OPP 계단 (${gx(step.growth_from)} → ${gx(step.growth_to)})` : 'OPP 계단', step ? `${sg(step.delta_mw)} mW` : '—',
        step ? `${step.cluster} ${fmt(step.mhz[0], 0)} → ${fmt(step.mhz[1], 0)} MHz · 최적 배치 ${sg(lim.opp_step_best_mw)} mW` : '범위 안에서 cluster OPP 상향 없음', step ? 'cal-t-fail' : '')}
      {tile(`분산 vs 집중 · ${gx(p0.growth)}`, svc.spread && svc.concentrate ? `${sg(svc.spread.total_mw - svc.concentrate.total_mw)} mW` : '—',
        svc.spread && svc.concentrate ? `분산 ${svc.spread.clusters.join('+')} ${fmt(svc.spread.total_mw, 1)} vs 집중 ${svc.concentrate.clusters.join('+')} ${fmt(svc.concentrate.total_mw, 1)}` : 'budget 만족 전략 부족',
        svc.spread && svc.concentrate && svc.spread.total_mw < svc.concentrate.total_mw ? 'pm-down' : '')}
      {tile('CPU 기인 BW power', p0.bw_mw === null || p0.bw_mw === undefined ? '—' : `${fmt(p0.bw_mw, 1)} → ${fmt(pN.bw_mw, 1)} mW`,
        p0.cpu_bw_mbs === null ? 'CPU → DRAM BW 없음' : `${fmt(p0.cpu_bw_mbs, 0)} → ${fmt(pN.cpu_bw_mbs, 0)} MB/s · ${s.bw_power ? `${(s.bw_power.mw_per_mbs * 1000).toFixed(1)} mW/GB/s (${s.bw_power.source === 'prediction' ? '조합 탐색 계수' : 'builtin'})` : ''}`)}
      {p0.bw_mw !== null && p0.bw_mw !== undefined && p0.reference && tile('CPU + DSU + BW', `${fmt(p0.reference.total_mw + p0.bw_mw, 1)} mW`,
        `SW ${gx(pN.growth)}: ${fmt((pN.reference?.total_mw ?? 0) + (pN.bw_mw ?? 0), 1)} mW · BW 비중 ${fmt((100 * p0.bw_mw) / (p0.reference.total_mw + p0.bw_mw), 0)}%`)}
    </section>
  )
}

/** CPU-02: CPU + DSU vs SW growth — current / best placement / best concentrate, OPP and timing markers. */
export function GrowthCurve({ s, yMax, withBw = true, height = 300 }: { s: Sweep; yMax?: number; withBw?: boolean; height?: number }) {
  const [ref, w] = useWidth<HTMLDivElement>(900)
  const tip = useTip()
  const pts = s.points.filter((p) => p.reference)
  if (pts.length < 2) return <div className="empty">곡선을 그릴 점이 부족합니다.</div>
  const H = height, l = 54, r = 20, t = 40, b = 40
  const g0 = pts[0].growth, g1 = pts[pts.length - 1].growth
  const X = (g: number) => l + ((g - g0) / (g1 - g0)) * (w - l - r)
  const conc = pts.map((p) => spreadVsConcentrate(p).concentrate?.total_mw ?? null)
  const bwLine = withBw && pts.every((p) => p.bw_mw !== null && p.bw_mw !== undefined) ? pts.map((p) => p.reference!.total_mw + (p.bw_mw ?? 0)) : null
  const hiRaw = (yMax ?? Math.max(...pts.map((p) => p.reference!.total_mw), ...conc.filter((v): v is number => v !== null), ...(bwLine ?? []))) * 1.1
  const step = hiRaw > 1200 ? 400 : hiRaw > 600 ? 200 : 100
  const hi = Math.ceil(hiRaw / step) * step
  const Y = (v: number) => t + (1 - v / hi) * (H - t - b)
  const line = (vals: (number | null)[]) => vals.map((v, i) => (v === null ? '' : `${i && vals[i - 1] !== null ? 'L' : 'M'}${X(pts[i].growth).toFixed(1)},${Y(v).toFixed(1)}`)).join(' ')
  const ticks: number[] = []
  for (let v = 0; v <= hi; v += step) ticks.push(v)
  const evs = s.events.filter((e) => e.which === 'reference' && e.mhz[1] > e.mhz[0])
  const lim = s.limits
  // the largest step on the reference line, labelled
  let jI = 1
  for (let i = 1; i < pts.length; i++) if (pts[i].reference!.total_mw - pts[i - 1].reference!.total_mw > pts[jI].reference!.total_mw - pts[jI - 1].reference!.total_mw) jI = i
  const jump = pts[jI].reference!.total_mw - pts[jI - 1].reference!.total_mw
  return (
    <div ref={ref}>
      <svg width={w} height={H} role="img" aria-label="SW 증가 배율에 따른 CPU + DSU 전력">
        {lim.timing_at !== null && lim.timing_at < g1 && <g>
          <rect x={X(Math.max(g0, lim.timing_at))} y={t} width={X(g1) - X(Math.max(g0, lim.timing_at))} height={H - t - b} fill="#F8E1DE" opacity={0.75} />
          <text x={X(g1) - 6} y={H - b - 8} fontSize={11} textAnchor="end" fill="#7F1D1D" fontWeight={600}>timing 여유 소진 {gx(lim.timing_at)} 이후 (latency +frame)</text></g>}
        {ticks.map((v) => <g key={v}><line x1={l} x2={w - r} y1={Y(v)} y2={Y(v)} stroke="#EFEAE2" />
          <text x={l - 8} y={Y(v) + 4} fontSize={11} textAnchor="end" className="mono" fill="#6B6558">{v}</text></g>)}
        <text x={4} y={t - 26} fontSize={11} fill="#6B6558">CPU + DSU mW</text>
        {pts.map((p) => <text key={p.growth} x={X(p.growth)} y={H - b + 17} fontSize={11} textAnchor="middle" className="mono" fill="#3B3F4A">{gx(p.growth)}</text>)}
        <text x={w - r} y={H - 5} fontSize={11} textAnchor="end" fill="#6B6558">SW 증가 배율 (instruction · runtime 같은 배율)</text>
        {evs.map((e, i) => {
          const x = (X(e.growth_from) + X(e.growth_to)) / 2
          return <g key={`${e.growth_from}-${e.cluster}`}>
            <line x1={x} x2={x} y1={t - 4} y2={H - b} stroke="#7A4B12" strokeWidth={1.2} strokeDasharray="4 3" />
            <text x={x} y={t - 8 - (i % 2) * 14} fontSize={11} textAnchor="middle" fill="#7A4B12" fontWeight={600}>{e.cluster} {fmt(e.mhz[0], 0)}→{fmt(e.mhz[1], 0)}</text></g>
        })}
        <path d={line(conc)} fill="none" stroke="#9A9387" strokeWidth={1.8} strokeDasharray="5 4" />
        {bwLine && <path d={line(bwLine)} fill="none" stroke="#0072B2" strokeWidth={1.6} strokeDasharray="2 3" />}
        <path d={line(pts.map((p) => p.reference!.total_mw))} fill="none" stroke="#4A5160" strokeWidth={2.2} />
        <path d={line(pts.map((p) => p.best?.total_mw ?? null))} fill="none" stroke="#2F6F68" strokeWidth={2.6} />
        {pts.map((p, i) => <g key={p.growth}>
          {conc[i] !== null && <circle cx={X(p.growth)} cy={Y(conc[i]!)} r={3} fill="#9A9387" stroke="#fff" strokeWidth={1.5} />}
          <circle cx={X(p.growth)} cy={Y(p.reference!.total_mw)} r={4} fill="#4A5160" stroke="#fff" strokeWidth={2} />
          {p.best && <circle cx={X(p.growth)} cy={Y(p.best.total_mw)} r={4} fill="#2F6F68" stroke="#fff" strokeWidth={2} />}
        </g>)}
        {jump > 0 && <text x={(X(pts[jI].growth) + X(pts[jI - 1].growth)) / 2 - 8} y={(Y(pts[jI].reference!.total_mw) + Y(pts[jI - 1].reference!.total_mw)) / 2} fontSize={12} fontWeight={600} textAnchor="end" className="mono" fill="#1F2430">{sg(jump)} mW</text>}
        {pts.map((p, i) => {
          const x0 = i === 0 ? l : (X(pts[i - 1].growth) + X(p.growth)) / 2
          const x1 = i === pts.length - 1 ? w - r : (X(p.growth) + X(pts[i + 1].growth)) / 2
          const mz = (m?: Record<string, number>) => (m ? mhzClusters(p).map((c) => fmt(m[c], 0)).join(' / ') : '—')
          const cs = spreadVsConcentrate(p)
          return <rect key={`hit-${p.growth}`} x={x0} y={t} width={x1 - x0} height={H - t - b} fill="transparent"
            {...tip({ title: `SW ${gx(p.growth)}`, head: { label: '현재 배치', value: `${fmt(p.reference!.total_mw, 1)} mW` },
              rows: [{ k: '최적 배치', v: p.best ? `${fmt(p.best.total_mw, 1)} mW` : '없음', color: '#2F6F68' },
                { k: '최적 집중', v: cs.concentrate ? `${fmt(cs.concentrate.total_mw, 1)} mW (${cs.concentrate.clusters.join('+')})` : '—', color: '#9A9387' },
                { section: `MHz (${mhzClusters(p).join(' / ')})` }, { k: '현재', v: mz(p.reference?.mhz) }, { k: '최적', v: mz(p.best?.mhz) },
                { k: 'DSU', v: `${fmt(p.reference?.mhz.dsu, 0)} MHz` },
                { section: 'BW · timing' }, { k: 'CPU → DRAM', v: p.cpu_bw_mbs === null ? '—' : `${fmt(p.cpu_bw_mbs, 0)} MB/s${p.bw_mw !== null && p.bw_mw !== undefined ? ` · ${fmt(p.bw_mw, 1)} mW` : ''}` },
                ...(p.bw_mw !== null && p.bw_mw !== undefined ? [{ k: '현재 + BW', v: `${fmt(p.reference!.total_mw + p.bw_mw, 1)} mW`, color: '#0072B2' }] : []),
                ...p.stages.map((st) => sweepStageTip(st))] })} />
        })}
      </svg>
      <div className="legend-row">
        <span className="legend-item"><span style={{ width: 14, height: 3, background: '#4A5160' }} />현재 배치 (측정 placement)</span>
        <span className="legend-item"><span style={{ width: 14, height: 3, background: '#2F6F68' }} />최적 배치 (MID 재분배)</span>
        <span className="legend-item"><span style={{ width: 14, height: 0, borderTop: '2px dashed #9A9387' }} />최적 집중 (cluster 1개)</span>
        {bwLine && <span className="legend-item"><span style={{ width: 14, height: 0, borderTop: '2px dotted #0072B2' }} />현재 + CPU 기인 BW</span>}
        <span className="legend-item"><span style={{ width: 0, height: 12, borderLeft: '2px dashed #7A4B12' }} />cluster OPP 상향</span>
      </div>
    </div>
  )
}

/** CPU-04: growth × distribution strategy (CPU + DSU mW), ★ = row minimum among budget-feasible. */
export function StrategyHeatmap({ s, onPick }: { s: Sweep; onPick?: (clusters: string[], growth: number) => void }) {
  const tip = useTip()
  const m = strategyMatrix(s.points)
  if (!m.cols.length) return <div className="empty">전략 비교 결과가 없습니다 (pool이 1개 cluster).</div>
  const vals = m.rows.flatMap((r) => r.cells.filter((c) => c && c.feasible).map((c) => c!.total_mw))
  const lo = Math.min(...vals), hi = Math.max(...vals)
  const RAMP = ['#EEF4F2', '#CFE3DD', '#9CC3BA', '#5E9C92', '#2F6F68']
  const bin = (v: number) => (hi > lo ? Math.min(4, Math.floor(((v - lo) / (hi - lo)) * 5)) : 0)
  return (
    <div className="table-x">
      <table className="cpu-hm">
        <thead><tr><th />{m.cols.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
        <tbody>{m.rows.map((r) => {
          const best = r.best !== null ? r.cells[r.best]!.total_mw : null
          return <tr key={r.growth}><th className="mono">{gx(r.growth)}</th>{r.cells.map((c, j) => {
            if (!c) return <td key={j} className="na" title="이 배율에서는 계산되지 않음 (대칭 cluster는 한쪽만 표시)">—</td>
            const k = bin(c.total_mw)
            return <td key={j} className={`${j === r.best ? 'best' : ''} ${c.feasible ? '' : 'infeasible'}`}
              style={c.feasible ? { background: RAMP[k], color: k >= 3 ? '#fff' : '#1F2430', cursor: onPick ? 'pointer' : undefined } : undefined}
              onClick={() => c.feasible && onPick?.(c.clusters, r.growth)}
              {...tip({ title: `SW ${gx(r.growth)} · ${m.cols[j].label}`, head: { label: 'CPU + DSU', value: `${fmt(c.total_mw, 1)} mW` },
                rows: [{ k: '행 최저 대비', v: best === null ? '—' : `${sg(c.total_mw - best)} mW` }, { k: 'budget', v: c.feasible ? '만족' : '미충족', tone: c.feasible ? undefined : 'bad' },
                  ...Object.entries(c.mhz).map(([cl, f]) => ({ k: cl, v: `${fmt(f, 0)} MHz` }))], foot: onPick ? '클릭 = 이 cluster 조합으로 분배 대상 pool 지정' : undefined })}>
              {j === r.best ? '★ ' : ''}{fmt(c.total_mw, c.total_mw < 1000 ? 1 : 0)}</td>
          })}</tr>
        })}</tbody>
      </table>
    </div>
  )
}

/** CPU-05: cluster MHz per growth (current / best), cells that changed from the previous row highlighted. */
export function OppStateTable({ s }: { s: Sweep }) {
  const cls = mhzClusters(s.points[0])
  const cols = [...cls, 'dsu']
  return (
    <div className="table-x">
      <table className="tb-mini-table cpu-opp">
        <thead><tr><th rowSpan={2}>SW</th><th colSpan={cols.length + 1}>현재 배치 (MHz · mW)</th><th colSpan={cols.length + 1}>최적 배치 (MHz · mW)</th></tr>
          <tr>{[0, 1].map((k) => [...cols.map((c) => <th key={`${k}-${c}`}>{c.replace(/^MID_/, '')}</th>), <th key={`${k}-mw`}>mW</th>])}</tr></thead>
        <tbody>{s.points.map((p, i) => {
          const prev = s.points[i - 1]
          const cells = (which: 'reference' | 'best') => [...cols.map((c) => {
            const v = p[which]?.mhz[c], pv = prev?.[which]?.mhz[c]
            return <td key={`${which}-${c}`} className={`mono ${prev && pv !== undefined && v !== pv ? 'chg' : ''}`}>{v === undefined ? '—' : fmt(v, 0)}</td>
          }), <td key={`${which}-mw`} className="mono">{fmt(p[which]?.total_mw, 1)}</td>]
          return <tr key={p.growth}><td className="mono">{gx(p.growth)}</td>{cells('reference')}{cells('best')}</tr>
        })}</tbody>
      </table>
    </div>
  )
}

export function GrowthSweepCards({ s, synthetic, busy, error, range, setRange, onRun, onPickPool, stale = false, locked = false }: {
  s: Sweep | null; synthetic: boolean; busy: boolean; error: string | null
  /** the curve was computed from other inputs (range or rebalance conditions) than the current ones */
  stale?: boolean
  /** another CPU calculation is running: the curve button waits for it */
  locked?: boolean
  range: { start: number; end: number; step: number }; setRange: (r: { start: number; end: number; step: number }) => void
  onRun: () => void; onPickPool?: (clusters: string[]) => void
}) {
  const num = (v: string, d: number) => (Number.isFinite(Number(v)) && v.trim() !== '' ? Number(v) : d)
  const controls = (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 12 }}>
      <span className="faint">SW ×</span>
      <input aria-label="SW 배율 시작" style={{ width: 52 }} type="number" step={0.05} value={range.start} onChange={(e) => setRange({ ...range, start: num(e.target.value, range.start) })} />
      <span className="faint">~</span>
      <input aria-label="SW 배율 끝" style={{ width: 52 }} type="number" step={0.05} value={range.end} onChange={(e) => setRange({ ...range, end: num(e.target.value, range.end) })} />
      <span className="faint">간격</span>
      <input aria-label="SW 배율 간격" style={{ width: 52 }} type="number" step={0.05} value={range.step} onChange={(e) => setRange({ ...range, step: num(e.target.value, range.step) })} />
      {stale && s && !busy && <span className="badge v-warn" title="범위나 분배 조건을 바꾼 뒤 아직 다시 계산하지 않았습니다">이전 조건</span>}
      <button className={`btn tb-mini ${stale || !s ? 'primary' : ''}`} disabled={busy || locked} onClick={onRun}>{busy ? '계산 중…' : stale && s ? '변경 반영' : '곡선 계산'}</button>
    </span>)
  return <>
    {error && <div className="err">{error}</div>}
    {s && <SweepTiles s={s} synthetic={synthetic} />}
    <div className="tb-grid">
      <Card id="cpu-growth" title="SW 증가 곡선 · CPU + DSU" defaultWide minHeight={160} actions={controls}
        note={s ? `${s.points.length}점 · ${(s.elapsed_ms / 1000).toFixed(1)} s${s.workers && s.workers > 1 ? ` (병렬 ${s.workers})` : ''} · 세로 점선 = cluster OPP 상향 · 빨간 띠 = Timing Budget stage 여유 소진 이후` : '조건이 정해지면 자동 계산'}
        help={<>같은 측정 profile과 분배 조건으로 SW 부하(instruction · runtime)를 배율만큼 늘려 다시 배치합니다. <b>허용치</b> = min(가장 큰 OPP 상향 직전 배율, Timing Budget stage의 SW 여유가 0이 되는 배율). 여유가 소진되면 fps는 유지돼도 pipeline latency가 늘어납니다.</>}>
        {s ? <GrowthCurve s={s} /> : <div className="empty">{busy ? '계산 중…' : '아직 계산되지 않았습니다.'}</div>}
        {s && s.limits.opp_step && <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>
          {gx(s.limits.opp_step.growth_from)} → {gx(s.limits.opp_step.growth_to)}에서 {s.limits.opp_step.cluster}가 {fmt(s.limits.opp_step.mhz[0], 0)} → {fmt(s.limits.opp_step.mhz[1], 0)} MHz로 올라갑니다 ({sg(s.limits.opp_step.delta_mw)} mW).
          {s.limits.opp_step_best_mw !== null && s.limits.opp_step_best_mw > 0.5 * s.limits.opp_step.delta_mw ? ' 재배치로도 이 계단을 피하지 못합니다 — SW 증가 예산을 이 배율 아래로 잡거나 task를 offload · 전용 core로 옮기는 안을 같이 봅니다.' : ' 재배치로 대부분 피할 수 있습니다.'}</div>}
      </Card>
      {s && <Card id="cpu-strat-hm" title="Cluster 배분 heatmap" note="SW 배율 × 배분 전략 · CPU + DSU mW · ★ = 행 최저 (budget 만족) · 빗금 = budget 미충족" minHeight={140}>
        <StrategyHeatmap s={s} onPick={onPickPool ? (c) => onPickPool(c) : undefined} />
      </Card>}
      {s && <Card id="cpu-opp-state" title="OPP 상태" note="SW 배율별 cluster MHz · 앞 행과 달라진 칸 강조" minHeight={140}>
        <OppStateTable s={s} />
      </Card>}
    </div>
  </>
}
