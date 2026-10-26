import { useMemo } from 'react'
import type { Ctx } from '../App'
import type { Dict } from '../lib/api'
import { experimentHref } from '../lib/experimentContext'
import { useAsync } from '../lib/route'
import { fmt } from '../lib/timingBudget'
import { ipSummary, libraryApi, range, type IpRow, type SensorCatalogRow, type SwTaskRow } from '../lib/library'
import { Card } from '../components/TimingCharts'
import { DataTable, type Column } from '../components/DataTable'

const TABS = [['ip', 'IP'], ['dvfs', 'DVFS'], ['comp', 'Compression'], ['sensor', 'Sensor'], ['sw', 'SW timing']] as const
type Tab = (typeof TABS)[number][0]

export function LibraryPage({ ctx }: { ctx: Ctx }) {
  const tab = (TABS.some(([k]) => k === ctx.params.tab) ? ctx.params.tab : 'ip') as Tab
  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ gap: 12, flexWrap: 'wrap' }}>
        <div className="seg" role="tablist" aria-label="Library">
          {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => ctx.navigate(undefined, { tab: k, sel: undefined }, true)}>{l}</button>)}
        </div>
        <span className="faint" style={{ fontSize: 12 }}>예측·탐색 계산에 쓰이는 입력값과 출처 (catalog · DT · 실측 · assumed)</span>
      </div>
      {tab === 'ip' && <IpTab ctx={ctx} />}
      {tab === 'dvfs' && <DvfsTab ctx={ctx} />}
      {tab === 'comp' && <CompTab />}
      {tab === 'sensor' && <SensorTab ctx={ctx} />}
      {tab === 'sw' && <SwTab ctx={ctx} />}
    </div>
  )
}

function IpTab({ ctx }: { ctx: Ctx }) {
  const q = useAsync(() => libraryApi.ips(), [])
  const rows = q.data?.items ?? []
  const sel = rows.find((r) => r.id === ctx.params.sel)
  const cols: Column<IpRow>[] = [
    { key: 'id', label: 'IP', width: 230, sticky: true, sort: (r) => r.id, render: (r) => <span className="mono">{r.id}</span> },
    { key: 'cat', label: 'Category', width: 100, sort: (r) => r.category, render: (r) => r.category },
    { key: 'hw', label: 'HW', width: 110, sort: (r) => ipSummary(r).hw, render: (r) => <span className="mono">{ipSummary(r).hw}</span> },
    { key: 'vdd', label: 'VDD', width: 110, sort: (r) => ipSummary(r).vdd, render: (r) => <span className="mono faint">{ipSummary(r).vdd}</span> },
    { key: 'dvfs', label: 'DVFS', width: 90, sort: (r) => ipSummary(r).dvfs, render: (r) => <span className="mono">{ipSummary(r).dvfs}</span> },
    { key: 'modes', label: 'modes', width: 70, align: 'right', sort: (r) => ipSummary(r).modes, render: (r) => ipSummary(r).modes || '—' },
    { key: 'comp', label: 'Compression', width: 220, sort: (r) => ipSummary(r).compression.length, render: (r) => { const c = ipSummary(r).compression; return c.length ? <span className="faint" style={{ fontSize: 12 }}>{c.join(', ')}</span> : <span className="faint">—</span> } },
    { key: 'src', label: '출처', width: 140, sort: (r) => ipSummary(r).source, render: (r) => <span className="badge">{ipSummary(r).source}</span> },
  ]
  return <div className="tb-grid">
    {q.error && <div className="err">{q.error}</div>}
    <Card id="lib-ip" title={`IP catalog (${rows.length})`} note="행 클릭 = 상세" defaultWide minHeight={200}>
      <div className="table-x"><DataTable id="lib.ip" columns={cols} rows={rows} rowKey={(r) => r.id} onRowClick={(r) => ctx.navigate(undefined, { sel: r.id }, true)} rowClass={(r) => (r.id === sel?.id ? 'selected' : '')} defaultSort={{ key: 'cat', dir: 1 }} /></div>
    </Card>
    {sel && <Card id="lib-ip-detail" title={sel.id} note={ipSummary(sel).note} defaultWide>
      <div className="workflow-actions">{[['ip_mode', 'Mode'], ['chain_size', 'Crop · scale']].map(([target, label]) => <button key={target} className="btn" onClick={() => ctx.navigate('whatif', { whatif_target: target, whatif_ip: sel.id })}>{label} 실험에서 지원 확인</button>)}</div>
      <IpCapabilities ip={sel} />
      <details><summary>원본 capability JSON</summary><pre className="lib-json">{JSON.stringify(sel.capabilities, null, 2)}</pre></details>
    </Card>}
  </div>
}

function DvfsTab({ ctx }: { ctx: Ctx }) {
  const q = useAsync(() => libraryApi.dvfs(), [])
  const tables = q.data?.items ?? []
  const t = tables.find((x) => x.id === ctx.params.sel) ?? tables[0]
  const doms = t ? Object.keys(t.domains).sort() : []
  const dom = doms.includes(ctx.params.dom ?? '') ? ctx.params.dom! : doms[0]
  const levels = t && dom ? t.domains[dom].levels : []
  const asvs = useMemo(() => [...new Set(levels.flatMap((l) => Object.keys(l.voltages)))].sort((a, b) => Number(a) - Number(b)), [levels])
  const note = t?.source && typeof t.source === 'object' ? String((t.source as Record<string, unknown>).note ?? '') : ''
  return <div className="tb-grid">
    {q.error && <div className="err">{q.error}</div>}
    {!tables.length && q.data && <div className="empty">DVFS table 없음</div>}
    {t && <Card id="lib-dvfs" title="DVFS table" note={`${t.soc_ref} · v${t.dvfs_version}${t.evt_hint ? ` · ${t.evt_hint}` : ''}`} defaultWide
      actions={<select className="input" value={t.id} onChange={(e) => ctx.navigate(undefined, { sel: e.target.value, dom: undefined }, true)} aria-label="DVFS table">{tables.map((x) => <option key={x.id} value={x.id}>{x.id}</option>)}</select>}>
      {note && <div className={`lib-note ${/SYNTHETIC|sample/i.test(note) ? 'warn' : ''}`}>{note}</div>}
      <div className="seg sm" role="tablist" aria-label="domain" style={{ margin: '8px 0' }}>
        {doms.map((d) => <button key={d} className={d === dom ? 'on' : ''} onClick={() => ctx.navigate(undefined, { dom: d }, true)}>{d} <span className="faint">({t.domains[d].levels.length})</span></button>)}
      </div>
      <div className="table-x"><table className="tb-mini-table" style={{ minWidth: 600 }}>
        <thead><tr><th>Level</th><th>MHz</th>{asvs.map((a) => <th key={a}>ASV{a} mV</th>)}</tr></thead>
        <tbody>{levels.map((l) => <tr key={l.level}><td className="mono">L{l.level}</td><td className="mono">{fmt(l.speed_mhz, 0)}</td>{asvs.map((a) => <td key={a} className="mono">{fmt(l.voltages[a], 2)}</td>)}</tr>)}</tbody>
      </table></div>
    </Card>}
  </div>
}

function CompTab() {
  const q = useAsync(() => libraryApi.socs(), [])
  return <div className="tb-grid">
    {q.error && <div className="err">{q.error}</div>}
    {(q.data?.items ?? []).map((s) => (
      <Card key={s.id} id={`lib-comp-${s.id}`} title={`${s.id} compression modes`} note={`${s.process_node ?? ''} · ${s.memory_type ?? ''}`}>
        <table className="tb-mini-table" style={{ width: '100%' }}>
          <thead><tr><th>mode</th><th>compressor</th><th>comp_ratio</th><th>의미</th></tr></thead>
          <tbody>{Object.entries(s.compression_modes ?? {}).map(([m, v]) => (
            <tr key={m}><td className="mono">{m}</td><td>{v.compressor ?? '—'}</td><td className="mono">{fmt(v.comp_ratio, 2)}</td>
              <td className="faint">{v.comp_ratio === undefined ? '—' : v.comp_ratio >= 1 ? '절감 없음 (탐색 제외)' : `BW ${Math.round((1 - v.comp_ratio) * 100)}% 절감`}</td></tr>))}</tbody>
        </table>
      </Card>))}
  </div>
}

function SensorTab({ ctx }: { ctx: Ctx }) {
  const c = useAsync(() => libraryApi.sensors(), [])
  const t = useAsync(() => libraryApi.sensorTiming(), [])
  const cols: Column<SensorCatalogRow>[] = [
    { key: 'sensor', label: 'Sensor', width: 140, sticky: true, sort: (r) => r.sensor_name, render: (r) => <span className="mono">{r.sensor_name}</span> },
    { key: 'board', label: 'Board', width: 120, sort: (r) => r.board, render: (r) => r.board },
    { key: 'modes', label: 'modes', width: 80, align: 'right', firstDir: -1, sort: (r) => r.mode_count, render: (r) => r.mode_count },
    { key: 'id', label: 'catalog', width: 220, sort: (r) => r.id, render: (r) => <span className="mono faint">{r.id}</span> },
    { key: 'experiment', label: '현재 scenario 실험', width: 180, render: (r) => <a href={`${experimentHref('whatif', { project_ref: ctx.project, scenario_id: ctx.scenario, variant_id: ctx.variant })}&whatif_target=sensor_mode&whatif_catalog=${encodeURIComponent(r.id)}`}>센서 교체 지원 확인 →</a> },
  ]
  return <div className="tb-grid">
    {c.error && <div className="err">{c.error}</div>}
    <Card id="lib-sensor" title={`Sensor catalog (${c.data?.total ?? 0})`} note="board별 DT mode set">
      <div className="table-x"><DataTable id="lib.sensor" columns={cols} rows={c.data?.items ?? []} rowKey={(r) => r.id} defaultSort={{ key: 'sensor', dir: 1 }} /></div>
    </Card>
    <Card id="lib-sensor-timing" title={`CIS timing profile (${t.data?.items.length ?? 0})`} note="readout · line timing">
      <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th>sensor</th><th>revision</th><th>modes</th></tr></thead>
        <tbody>{(t.data?.items ?? []).map((p) => <tr key={p.id}><td className="mono">{p.sensor_name}</td><td className="faint" style={{ fontSize: 12 }}>{p.revision ?? '—'}</td><td className="mono">{p.modes.length}</td></tr>)}</tbody>
      </table>
    </Card>
  </div>
}

function IpCapabilities({ ip }: { ip: IpRow }) {
  const dict = (v: unknown): Dict => v && typeof v === 'object' && !Array.isArray(v) ? v as Dict : {}
  const sim = dict(ip.capabilities.sim)
  const modes = [{ role: '공통', data: sim }, ...Object.entries(dict(sim.role_modes)).map(([role, data]) => ({ role, data: dict(data) }))]
    .flatMap(({ role, data }) => Object.entries(dict(data.modes)).map(([mode, raw]) => ({ role, mode, value: dict(raw) })))
  const geometry = dict(sim.geometry)
  return <>
    <p className="faint">catalog 모델 입력입니다. 실제 변경 가능 여부와 정렬·배율·FPS 제약은 선택 scenario의 실험 화면에서 검증합니다.</p>
    {modes.length > 0 ? <div className="table-x"><table className="tb-mini-table" style={{ width: '100%' }}>
      <thead><tr><th>역할</th><th>Mode</th><th>PPC</th><th>단위 power mW/MP</th><th>근거 · 상태</th></tr></thead>
      <tbody>{modes.map((m) => <tr key={`${m.role}:${m.mode}`}><td>{m.role}</td><td>{m.mode}</td><td>{String(m.value.ppc ?? sim.ppc ?? '미정')}</td><td>{String(m.value.unit_power_mw_mp ?? '미정')}</td><td>{String(dict(m.value.evidence).status ?? m.value.source ?? sim.source ?? '출처 미정')}{m.value.explorable === false ? ' · 탐색 제외' : ''}</td></tr>)}</tbody>
    </table></div> : <p className="faint">Mode별 모델 입력 없음</p>}
    {Object.keys(geometry).length > 0 && <details open><summary>Crop · scale 제약</summary><pre className="lib-json">{JSON.stringify(geometry, null, 2)}</pre></details>}
  </>
}

function SwTab({ ctx }: { ctx: Ctx }) {
  const all = ctx.params.all === '1'
  const q = useAsync(() => libraryApi.swTiming(all ? undefined : ctx.scenario), [ctx.scenario, all])
  const cols: Column<SwTaskRow>[] = [
    { key: 'task', label: 'SW task', width: 200, sticky: true, sort: (r) => r.task, render: (r) => <span className="mono">{r.task}</span> },
    ...(all ? [{ key: 'sc', label: 'Scenario', width: 180, sort: (r: SwTaskRow) => r.scenario_id, render: (r: SwTaskRow) => <span className="faint">{r.scenario_id}</span> }] : []),
    { key: 'n', label: 'variants', width: 80, align: 'right', sort: (r) => r.variants, render: (r) => r.variants },
    { key: 'min', label: 'min ms', width: 100, align: 'right', sort: (r) => r.min_ms?.[1] ?? -1, render: (r) => <span className="mono">{range(r.min_ms, 2)}</span> },
    { key: 'mean', label: 'mean ms', width: 100, align: 'right', firstDir: -1, sort: (r) => r.mean_ms?.[1] ?? -1, render: (r) => <span className="mono">{range(r.mean_ms, 2)}</span> },
    { key: 'max', label: 'max ms', width: 100, align: 'right', firstDir: -1, sort: (r) => r.max_ms?.[1] ?? -1, render: (r) => <span className="mono">{range(r.max_ms, 2)}</span> },
    { key: 'lat', label: 'latency ms', width: 100, align: 'right', sort: (r) => r.latency_ms?.[1] ?? -1, render: (r) => <span className="mono">{range(r.latency_ms, 2)}</span> },
    { key: 'src', label: '출처', width: 150, sort: (r) => r.source.join(','), render: (r) => r.source.map((s) => <span key={s} className={`badge ${/assumed|unspecified/.test(s) ? 'v-warn' : 'v-ok'}`} style={{ marginRight: 4 }}>{s}</span>) },
    { key: 'br', label: 'bitrate 비례', width: 90, sort: (r) => (r.bitrate_scaled ? 1 : 0), render: (r) => (r.bitrate_scaled ? '예' : '—') },
  ]
  return <div className="tb-grid">
    <div className="seg sm" role="group" aria-label="범위" style={{ gridColumn: '1 / -1', justifySelf: 'start' }}>
      <button className={!all ? 'on' : ''} onClick={() => ctx.navigate(undefined, { all: undefined }, true)}>현재 scenario</button>
      <button className={all ? 'on' : ''} onClick={() => ctx.navigate(undefined, { all: '1' }, true)}>전체</button>
    </div>
    {q.error && <div className="err">{q.error}</div>}
    <Card id="lib-sw" title={`SW timing 가정 (${q.data?.tasks.length ?? 0})`} note="variant 간 범위 · Timing Budget·조합 탐색 입력" defaultWide>
      <div className="table-x"><DataTable id="lib.sw" columns={cols} rows={q.data?.tasks ?? []} rowKey={(r) => `${r.scenario_id}:${r.task}`} defaultSort={{ key: 'max', dir: -1 }} /></div>
    </Card>
    {!all && ctx.scenario && ctx.variant && <SwSetsCard scenario={ctx.scenario} variant={ctx.variant} />}
    <Card id="lib-sw-meas" title={`SW task 실측 (${q.data?.measured.length ?? 0})`} note="measurement evidence (Perfetto)" defaultWide>
      {q.data?.measured.length ? <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th>task</th><th>variant</th><th>mean ms</th><th>p95 ms</th><th>max ms</th><th>evidence</th></tr></thead>
        <tbody>{q.data.measured.map((m) => <tr key={`${m.evidence_id}:${m.task}`}><td className="mono">{m.task}{m.synthetic && <span className="badge v-warn" title="합성 fixture — 실제 측정 아님">합성</span>}</td><td className="faint">{m.variant_id}</td><td className="mono">{fmt(m.mean_ms, 2)}</td><td className="mono">{fmt(m.p95_ms, 2)}</td><td className="mono">{fmt(m.max_ms, 2)}</td><td><a href={`#/calibration?m=${encodeURIComponent(m.evidence_id)}&all=1`}>{m.evidence_id.slice(0, 24)}…</a></td></tr>)}</tbody>
      </table> : <div className="empty">실측 SW task 없음</div>}
    </Card>
  </div>
}

/** P2: one variant's SW timing as sets — defined table (hash) vs each measured SW build (SoC) — mean / max and Δ% vs defined. */
function SwSetsCard({ scenario, variant }: { scenario: string; variant: string }) {
  const q = useAsync(() => libraryApi.swTimingSets(scenario, variant), [scenario, variant])
  const sets = q.data?.sets ?? []
  const f = (x?: number | null) => (x == null ? '—' : x.toFixed(2))
  return <Card id="lib-sw-sets" title={`SW timing set 비교 · ${variant}`} defaultWide
    note="정의값(assumed)은 사용 값의 hash로, 실측은 SW build · SoC별로 구분 (SW profile 이름만으로는 timing이 같다는 보장 없음) · Δ = 정의 mean 대비">
    {q.error && <div className="err">{q.error}</div>}
    {q.data && !q.data.tasks.length && <div className="empty">이 variant에는 SW timing 정의 · 실측이 없습니다.</div>}
    {q.data && q.data.tasks.length > 0 && <div className="table-x"><table className="tb-mini-table" style={{ width: '100%' }}>
      <thead><tr><th>task</th>{sets.map((s) => <th key={s.id} title={[s.sw_ref ?? '정의값', s.value_source?.join(', '), s.evidence ? `evidence ${s.evidence}` : null, s.latest ? `최근 ${s.latest}` : null].filter(Boolean).join(' · ')}>
        <span className={s.synthetic ? 'faint' : ''}>{s.label}</span></th>)}</tr>
        <tr className="faint" style={{ fontSize: 11 }}><th /> {sets.map((s) => <th key={s.id}>mean / max ms{s.source === 'measured' ? ' · Δ' : ''}</th>)}</tr></thead>
      <tbody>{q.data.tasks.map((t) => <tr key={t.task}><td className="mono">{t.task}</td>
        {sets.map((s) => { const c = t.values[s.id]
          return <td key={s.id} className="mono">{c ? <>{f(c.mean_ms)} / {f(c.max_ms)}{c.delta_pct != null && <span style={{ marginLeft: 6, color: Math.abs(c.delta_pct) >= 20 ? 'var(--del-text)' : 'var(--muted)' }}>{c.delta_pct > 0 ? '+' : ''}{c.delta_pct}%</span>}</> : <span className="faint">—</span>}</td> })}
      </tr>)}</tbody>
    </table></div>}
  </Card>
}
