import { fmt, type Residency, type Subsystem, type SubsystemRoute } from '../lib/timingBudget'
import { Hint } from './Hint'

const SRC: Record<string, [string, string]> = { measured: ['v-ok', '실측'], fitted: ['v-info', '보정'], spec: ['v-info', 'spec'], assumed: ['v-na', '가정'] }
export function SourceBadge({ source }: { source?: string | null }) {
  if (!source) return <span className="faint">—</span>
  const [cls, label] = SRC[source] ?? ['v-na', source]
  return <span className={`badge ${cls}`}>{label}</span>
}

const pct = (v?: number) => (v == null ? '—' : `${(v * 100).toFixed(v < 0.1 ? 1 : 0)}%`)

/** Routes of a subsystem: ``routes`` when the server lists several, else the single ``route``. */
export function subsystemRoutes(s: Subsystem): SubsystemRoute[] {
  return s.routes?.length ? s.routes : s.route ? [s.route] : []
}

/** X-03: one mcps-v1 subsystem — unit load, domain operating point, per-stream deadline slack, route latency
 * against its target and the wake sources. Everything is read from report.subsystems[node]. */
export function SubsystemView({ node, s }: { node: string; s: Subsystem }) {
  const routes = subsystemRoutes(s)
  return <div className="ss-grid" data-testid={`subsystem-${node}`}>
    <div>
      <div className="faint t-caption">unit 부하 · {s.model} · 합계 {fmt(s.mw, 2)} mW{!s.feasible && <b style={{ color: 'var(--del-text)' }}> · 실행 불가</b>}</div>
      <div style={{ overflowX: 'auto' }}>
        <table className="tb-mini-table" style={{ width: '100%' }}>
          <thead><tr><th>unit</th><th>kind</th><th style={{ textAlign: 'right' }}>MCPS</th><th>util / 목표</th><th style={{ textAlign: 'right' }}>mW</th><th>출처</th></tr></thead>
          <tbody>
            {(s.units ?? []).map((u) => (
              <tr key={u.id} data-testid={`ss-unit-${u.id}`}>
                <td className="mono">{u.id}{u.gated && <span className="faint"> · gated</span>}</td>
                <td className="faint">{u.kind}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{u.load_mcps == null ? '—' : fmt(u.load_mcps, 1)}</td>
                <td>{u.util == null ? <span className="faint">—</span> : <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                  <span className="ss-bar" style={{ width: 80 }}><span className={u.target_util != null && u.util > u.target_util ? 'bad' : ''} style={{ width: `${Math.min(100, u.util * 100)}%` }} />
                    {u.target_util != null && <i style={{ left: `${Math.min(100, u.target_util * 100)}%` }} />}</span>
                  <span className="mono t-caption">{pct(u.util)}{u.target_util != null && <span className="faint"> / {pct(u.target_util)}</span>}</span></span>}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{fmt(u.mw, 2)}</td>
                <td><SourceBadge source={u.value_source} /></td>
              </tr>))}
          </tbody>
        </table>
      </div>
      {(s.unattributed_units?.length ?? 0) > 0 && <div className="faint t-caption">power 모델 없는 unit (mW 합계 제외): {s.unattributed_units!.join(', ')}</div>}
    </div>
    <div style={{ display: 'grid', gap: 10, alignContent: 'start' }}>
      {Object.entries(s.domains ?? {}).map(([d, v]) => (
        <div key={d} data-testid={`ss-domain-${d}`}>
          <div className="faint t-caption">domain {d} 운영점{v.pinned && ' (고정)'}</div>
          <div><b className="mono">{v.freq_mhz == null ? '운영점 없음' : `${fmt(v.freq_mhz, 0)} MHz`}</b>
            {v.max_util != null && <span className="faint"> · 최대 util {pct(v.max_util)}</span>}
            {(v.levels_mhz?.length ?? 0) > 0 && <span className="faint t-caption"> · level {v.levels_mhz!.indexOf(v.freq_mhz ?? -1) + 1 || '?'} / {v.levels_mhz!.length}</span>}</div>
        </div>))}
      {(s.deadline_slack?.length ?? 0) > 0 && <div>
        <div className="faint t-caption">stream deadline 여유 (주기 대비)</div>
        {s.deadline_slack!.map((d) => (
          <div key={d.stream} style={{ display: 'flex', gap: 8, alignItems: 'center' }} data-testid={`ss-slack-${d.stream}`}>
            <span className="mono" style={{ minWidth: 64 }}>{d.stream}</span>
            <span className="ss-bar" style={{ flex: 1 }}><span className={d.slack_ms < 0 ? 'bad' : ''} style={{ width: `${Math.max(0, Math.min(100, (d.slack_ms / d.period_ms) * 100))}%` }} /></span>
            <span className="mono t-caption">{fmt(d.slack_ms, 2)} / {fmt(d.period_ms, 1)} ms</span>
            <span className="faint t-caption">{d.unit}</span>
          </div>))}
      </div>}
      {routes.map((r) => (
        <div key={r.id} data-testid={`ss-route-${r.id}`}>
          <div className="faint t-caption">route {r.id} ({r.kind}) latency</div>
          <div><b className="mono" style={{ color: r.latency_ok === false ? 'var(--del-text)' : undefined }}>{r.latency_ms == null ? '—' : `${fmt(r.latency_ms, 1)} ms`}</b>
            {r.latency_target_ms != null && <span className="faint"> · 목표 ≤ {fmt(r.latency_target_ms, 0)} ms {r.latency_ok === false ? '✗' : '✓'}</span>}
            <Hint label="route 구성" text={<>buffering {fmt(r.buffering_ms ?? 0, 1)} ms + 처리 {fmt(r.processing_ms ?? 0, 2)} ms<br />{r.stages.join(' → ')}</>} /></div>
        </div>))}
      {(s.wake?.sources.length ?? 0) > 0 && <div>
        <div className="faint t-caption">wake source · {fmt(s.wake!.per_s, 2)} wake/s</div>
        {s.wake!.sources.map((w, i) => <div key={`${w.kind}-${i}`} className="mono t-caption">{w.kind} · {fmt(w.per_s, 2)}/s{w.every_ms != null && ` (${fmt(w.every_ms, 0)} ms마다)`}{w.mb != null && ` · ${fmt(w.mb, 2)} MB`}</div>)}
      </div>}
    </div>
  </div>
}

/** wake-residency-v1: wake sources and, with coefficients, the AP wake / MIF state split. */
export function ResidencyView({ r }: { r: Residency }) {
  const ok = r.status === 'ok'
  return <div data-testid="residency">
    <div className="faint t-caption">wake residency · {r.screen_on ? '화면 on' : '화면 off'} · {fmt(r.wakeups_per_s, 2)} wake/s</div>
    {ok ? <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
      <span><span className="faint">합계 </span><b className="mono">{fmt(r.mw ?? 0, 2)} mW</b></span>
      <span><span className="faint">AP wake </span><span className="mono">{fmt(r.cpu_wake_mw ?? 0, 2)} mW</span></span>
      <span><span className="faint">MIF state </span><span className="mono">{fmt(r.mif_state_mw ?? 0, 2)} mW</span></span>
      <span><span className="faint">MIF active </span><span className="mono">{r.mif_active_ratio == null ? '—' : `${(r.mif_active_ratio * 100).toFixed(3)}%`}</span></span>
      <SourceBadge source={r.value_source} />
    </div> : <div className="faint">{r.note ?? '계수 없음: wake 횟수만 보고'}</div>}
    <table className="tb-mini-table" style={{ width: '100%', marginTop: 4 }}>
      <thead><tr><th>node</th><th>kind</th><th style={{ textAlign: 'right' }}>/s</th><th style={{ textAlign: 'right' }}>주기</th><th style={{ textAlign: 'right' }}>MB</th><th style={{ textAlign: 'right' }}>burst</th></tr></thead>
      <tbody>{r.sources.map((s, i) => <tr key={`${s.node}-${s.kind}-${i}`}>
        <td className="mono">{s.node}</td><td className="faint">{s.kind}</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(s.per_s, 2)}</td>
        <td className="mono" style={{ textAlign: 'right' }}>{s.every_ms == null ? '—' : `${fmt(s.every_ms, 0)} ms`}</td>
        <td className="mono" style={{ textAlign: 'right' }}>{s.mb == null ? '—' : fmt(s.mb, 2)}</td>
        <td className="mono" style={{ textAlign: 'right' }}>{s.burst_ms == null ? '—' : `${fmt(s.burst_ms, 2)} ms`}</td></tr>)}</tbody>
    </table>
  </div>
}

export function SubsystemCard({ subsystems, residency }: { subsystems?: Record<string, Subsystem>; residency?: Residency | null }) {
  const entries = Object.entries(subsystems ?? {})
  return <div style={{ display: 'grid', gap: 14 }}>
    {entries.map(([node, s]) => <div key={node}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{node}{s.basis && <Hint label="모델 근거" text={s.basis} />}</div>
      <SubsystemView node={node} s={s} /></div>)}
    {residency && <ResidencyView r={residency} />}
  </div>
}
