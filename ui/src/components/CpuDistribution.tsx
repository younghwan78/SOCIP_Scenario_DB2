// CPU what-if, distribution view (CPU-07 · CPU-08 · CPU-10):
// distribution-ratio curve per target cluster, OPP headroom gauge per cluster, and the same profile's
// SW-growth curve on two projects' CPU topologies with one y axis.
import { useWidth } from './Charts'
import { useTip } from './ChartTip'
import { Card } from './TimingCharts'
import { GrowthCurve } from './GrowthSweep'
import { fmt } from '../lib/timingBudget'
import { firstStepUp, sweepYMax, type GrowthSweep } from '../lib/growthSweep'
import type { CpuRebalance, RatioCurve } from '../lib/rebalance'

const gx = (g: number) => `×${g.toFixed(g * 10 % 1 === 0 ? 1 : 2)}`
const sg = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(d)}`)
const BAND = ['#EEF2F7', '#E3ECE9', '#F6EEDC', '#F3E2E0', '#E9E4F2', '#E0EEF5']
const LINE = ['#0072B2', '#2F6F68', '#B26B00', '#7A3E9D']

/** OPP signature of a point (pool clusters, DSU excluded) — one band colour per distinct signature. */
const sigOf = (mhz: Record<string, number>) => Object.entries(mhz).filter(([k]) => k !== 'dsu').map(([k, v]) => `${k.replace(/^MID_/, '')} ${v}`).join(' / ')

/** CPU-07: x = share of the movable util on the target cluster, y = CPU + DSU mW, OPP state bands. */
export function RatioCurves({ r }: { r: CpuRebalance }) {
  const [ref, w] = useWidth<HTMLDivElement>(900)
  const tip = useTip()
  const curves = (r.ratio_curves ?? []).filter((c) => c.points.length > 1)
  if (!curves.length) return <div className="empty">분배 비율 곡선 없음 (API 업데이트 필요 또는 이동 가능 task 없음)</div>
  const all = curves.flatMap((c) => c.points.map((p) => p.total_mw))
  const lo = Math.floor(Math.min(...all) * 0.95 / 10) * 10, hi = Math.ceil(Math.max(...all) * 1.03 / 10) * 10
  const cols = Math.min(curves.length, w > 900 ? 3 : w > 560 ? 2 : 1)
  const cw = Math.floor((w - (cols - 1) * 14) / cols)
  const H = 210, l = 44, rr = 22, t = 14, b = 44
  const X = (u: number) => l + (u / 100) * (cw - l - rr)
  const Y = (v: number) => t + (1 - (v - lo) / (hi - lo || 1)) * (H - t - b)
  const sigs = [...new Set(curves.flatMap((c) => c.points.map((p) => sigOf(p.mhz))))]
  const one = (c: RatioCurve, k: number) => {
    const pts = c.points
    const best = c.best_index !== null ? pts[c.best_index] : null
    const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.util_pct).toFixed(1)},${Y(p.total_mw).toFixed(1)}`).join(' ')
    return <div key={c.target} style={{ width: cw }}>
      <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 2 }}>→ {c.target} <span className="faint" style={{ fontWeight: 400 }}>
        현재 {fmt(c.start_util_pct, 0)}% · 최저 {best ? `${fmt(best.util_pct, 0)}% ${fmt(best.total_mw, 1)} mW (${sg(best.total_mw - pts[0].total_mw)})` : '—'}</span></div>
      <svg width={cw} height={H} role="img" aria-label={`${c.target}로 옮긴 util 비율에 따른 CPU 전력`}>
        {pts.map((p, i) => {
          const x0 = i === 0 ? l : (X(pts[i - 1].util_pct) + X(p.util_pct)) / 2
          const x1 = i === pts.length - 1 ? cw - rr : (X(p.util_pct) + X(pts[i + 1].util_pct)) / 2
          return <rect key={`b${i}`} x={x0} y={H - b + 4} width={Math.max(0, x1 - x0)} height={8} fill={BAND[sigs.indexOf(sigOf(p.mhz)) % BAND.length]} stroke="#fff" strokeWidth={0.5} />
        })}
        {[0, 25, 50, 75, 100].map((u) => <g key={u}><line x1={X(u)} x2={X(u)} y1={t} y2={H - b} stroke="#EFEAE2" />
          <text x={X(u)} y={H - b + 26} fontSize={10.5} textAnchor="middle" className="mono" fill="#6B6558">{u}%</text></g>)}
        {[lo, (lo + hi) / 2, hi].map((v) => <text key={v} x={l - 6} y={Y(v) + 4} fontSize={10.5} textAnchor="end" className="mono" fill="#6B6558">{fmt(v, 0)}</text>)}
        <line x1={X(c.start_util_pct)} x2={X(c.start_util_pct)} y1={t} y2={H - b} stroke="#1F2430" strokeDasharray="3 3" />
        <path d={d} fill="none" stroke={LINE[k % LINE.length]} strokeWidth={2} />
        {pts.map((p, i) => <circle key={i} cx={X(p.util_pct)} cy={Y(p.total_mw)} r={i === c.best_index ? 5.5 : 3.5}
          fill={p.feasible ? (i === c.best_index ? '#2F855A' : LINE[k % LINE.length]) : '#fff'} stroke={p.feasible ? '#fff' : '#B42318'} strokeWidth={p.feasible ? 1.5 : 1.6}
          {...tip({ title: i === 0 ? '현재 배치' : `+ ${p.moved_unit} → ${c.target}`, head: { label: 'CPU + DSU', value: `${fmt(p.total_mw, 1)} mW` },
            rows: [{ k: `${c.target} 비중`, v: `${fmt(p.util_pct, 1)}% util` }, { k: '현재 대비', v: `${sg(p.total_mw - pts[0].total_mw)} mW` },
              { k: 'budget', v: p.feasible ? '만족' : '미충족 (task 지연)', tone: p.feasible ? undefined : 'bad' as const },
              ...Object.entries(p.mhz).map(([cl, f]) => ({ k: cl, v: `${fmt(f, 0)} MHz` }))] })} />)}
      </svg>
    </div>
  }
  return (
    <div ref={ref}>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>{curves.map(one)}</div>
      <div className="legend-row">
        <span className="legend-item faint">점선 = 현재 비중 · ● 녹색 = budget 만족 최저 · ○ 빨강 = budget 미충족 · 아래 띠 = OPP 상태 (색 = cluster MHz 조합)</span>
        {sigs.slice(0, 6).map((sgn, i) => <span key={sgn} className="legend-item"><span style={{ width: 12, height: 8, background: BAND[i % BAND.length], border: '1px solid #DDD' }} /><span className="mono" style={{ fontSize: 11 }}>{sgn}</span></span>)}
      </div>
    </div>
  )
}

/** CPU-08: per cluster OPP ladder — where it runs now / with the best split, util to drop one step, SW growth to go up. */
export function OppGauge({ r, sweep }: { r: CpuRebalance; sweep: GrowthSweep | null }) {
  const rows = r.clusters.filter((c) => c.in_pool || r.reference.mhz[c.name] !== undefined)
  const bRef = Object.fromEntries(r.boundaries.reference.map((b) => [b.cluster, b]))
  const bBest = Object.fromEntries((r.boundaries.best ?? []).map((b) => [b.cluster, b]))
  const W = 260
  return (
    <table className="tb-mini-table cpu-gauge" style={{ width: '100%' }}>
      <thead><tr><th>cluster</th><th>OPP 사다리 (MHz) · ▲ 현재 · ◆ 최적</th><th>현재 → 최적</th><th>한 단계 ↓ 위해 뺄 util</th><th>SW 증가 시 ↑</th></tr></thead>
      <tbody>{rows.map((c) => {
        const opps = c.opps_mhz.length ? c.opps_mhz : [r.reference.mhz[c.name]]
        const n = opps.length
        const pos = (f: number | undefined) => (f === undefined ? null : opps.findIndex((o) => o >= f - 1e-6))
        const X = (i: number) => 16 + (n > 1 ? (i / (n - 1)) * (W - 32) : (W - 32) / 2)
        const iRef = pos(r.reference.mhz[c.name]), iBest = pos(r.best?.mhz[c.name])
        const br = bRef[c.name], bb = bBest[c.name]
        const up = firstStepUp(sweep, c.name)
        return <tr key={c.name}>
          <td className="mono"><b>{c.name}</b> <span className="faint">{c.cores}c{c.in_pool ? '' : ' · pool 밖'}</span></td>
          <td><svg width={W} height={34} aria-hidden="true">
            <line x1={X(0)} x2={X(n - 1)} y1={14} y2={14} stroke="#CFC8BC" strokeWidth={2} />
            {opps.map((o, i) => <g key={o}><circle cx={X(i)} cy={14} r={3} fill={iRef !== null && i <= iRef ? '#4A5160' : '#E6E1D8'} />
              <text x={X(i)} y={31} fontSize={9.5} textAnchor="middle" className="mono" fill="#6B6558">{fmt(o, 0)}</text></g>)}
            {iRef !== null && iRef >= 0 && <text x={X(iRef)} y={9} fontSize={10} textAnchor="middle" fill="#1F2430">▲</text>}
            {iBest !== null && iBest >= 0 && iBest !== iRef && <text x={X(iBest)} y={9} fontSize={10} textAnchor="middle" fill="#2F855A">◆</text>}
          </svg></td>
          <td className="mono">{fmt(r.reference.mhz[c.name], 0)}{r.best && r.best.mhz[c.name] !== r.reference.mhz[c.name] ? <b className={r.best.mhz[c.name] < r.reference.mhz[c.name] ? 'pm-down' : 'pm-up'}> → {fmt(r.best.mhz[c.name], 0)}</b> : ''}</td>
          <td className="mono">{br?.boosted_by?.length ? <span className="badge v-warn">budget ↑ {br.boosted_by.slice(0, 2).join(', ')}</span>
            : br?.next_lower_mhz ? <>{fmt(br.delta_util_needed, 1)} <span className="faint">→ {fmt(br.next_lower_mhz, 0)} MHz{bb?.delta_util_needed !== undefined && bb.delta_util_needed !== br.delta_util_needed ? ` · 최적 배치 ${fmt(bb.delta_util_needed, 1)}` : ''}</span></> : <span className="faint">최저 OPP</span>}</td>
          <td className="mono">{up ? <span className="badge v-warn" style={{ whiteSpace: 'nowrap' }}>{gx(up.growth_to)}: {fmt(up.mhz[0], 0)}→{fmt(up.mhz[1], 0)} ({sg(up.delta_mw)} mW)</span> : sweep ? <span className="faint">범위 안 없음</span> : '—'}</td>
        </tr>
      })}</tbody>
    </table>
  )
}

/** CPU-10: same profile, two topologies, one y axis. */
export function GrowthCompare({ a, b, aName, bName, busy, error }: { a: GrowthSweep | null; b: GrowthSweep | null; aName: string; bName: string; busy: boolean; error: string | null }) {
  const yMax = sweepYMax([a, b])
  const tol = (s: GrowthSweep | null) => (s ? (s.limits.tolerance === null ? `> ${gx(s.points[s.points.length - 1].growth)}` : gx(s.limits.tolerance)) : '—')
  const at = (s: GrowthSweep | null, i: number) => s?.points[i]?.reference?.total_mw ?? null
  return (
    <Card id="cpu-growth-cmp" title="과제 비교 · SW 증가 곡선" defaultWide minHeight={160}
      note="같은 측정 profile · 같은 budget을 두 과제 CPU topology에 적용 · y축 공통"
      help={<>사내 topology(power_model_params)를 등록하면 E2600 · E2700 · 후속 과제 CPU 구성에서 같은 SW 부하 증가가 전력과 OPP 계단에 어떻게 반영되는지 나란히 봅니다.</>}>
      {error && <div className="err">{error}</div>}
      <table className="tb-mini-table" style={{ width: '100%', marginBottom: 8 }}>
        <thead><tr><th /><th>{aName}</th><th>{bName}</th><th>차이</th></tr></thead>
        <tbody>
          <tr><td className="faint">현재 배치 · 시작 배율</td><td className="mono">{fmt(at(a, 0), 1)} mW</td><td className="mono">{fmt(at(b, 0), 1)} mW</td>
            <td className="mono">{at(a, 0) !== null && at(b, 0) !== null ? `${sg(at(b, 0)! - at(a, 0)!)} mW` : ''}</td></tr>
          <tr><td className="faint">현재 배치 · 끝 배율</td><td className="mono">{fmt(at(a, (a?.points.length ?? 1) - 1), 1)} mW</td><td className="mono">{fmt(at(b, (b?.points.length ?? 1) - 1), 1)} mW</td><td /></tr>
          <tr><td className="faint">SW 증가 허용치</td><td className="mono">{tol(a)}</td><td className="mono">{busy && !b ? '계산 중…' : tol(b)}</td><td /></tr>
          <tr><td className="faint" title="허용치를 정한 계단 — 비용이 5 mW 또는 5% 이상인 첫 상향">첫 OPP 계단</td><td className="mono">{a?.limits.opp_step ? `${a.limits.opp_step.cluster} ${gx(a.limits.opp_step.growth_to)} ${sg(a.limits.opp_step.delta_mw)} mW` : '—'}</td>
            <td className="mono">{b?.limits.opp_step ? `${b.limits.opp_step.cluster} ${gx(b.limits.opp_step.growth_to)} ${sg(b.limits.opp_step.delta_mw)} mW` : '—'}</td><td /></tr>
        </tbody>
      </table>
      {[[aName, a], [bName, b]].map(([name, s]) => {
        const sw = s as GrowthSweep | null
        const bad = (sw?.points ?? []).filter((p) => p.reference && !p.reference.feasible).length
        return bad ? <div key={name as string} className="lib-note warn" style={{ marginBottom: 6 }}>{name as string}: 현재(측정) 배치가 {bad}/{sw!.points.length}점에서 budget 미충족 — 이 topology에서는 측정 배치 그대로 fps를 못 맞춥니다 (cluster가 fmax에 포화). 최적 배치 선으로 비교하고, topology가 SAMPLE이면 사내 값으로 교체 후 다시 봅니다.</div> : null
      })}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: 12 }}>
        <div><b style={{ fontSize: 12.5 }}>{aName}</b>{a ? <GrowthCurve s={a} yMax={yMax} height={240} withBw={false} /> : <div className="empty">—</div>}</div>
        <div><b style={{ fontSize: 12.5 }}>{bName}</b>{b ? <GrowthCurve s={b} yMax={yMax} height={240} withBw={false} /> : <div className="empty">{busy ? '계산 중…' : '—'}</div>}</div>
      </div>
    </Card>
  )
}
