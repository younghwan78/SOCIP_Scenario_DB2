// Pipeline "Sim 입력" lens: per node what the simulation charges — cadence (frame path or own cadence),
// execution time, load term (SW CPU ms/s · HW duty %), power / BW — plus defined-vs-measured checks.
import { useMemo } from 'react'
import type { SimInputCheck, SimInputRow, SimInputs } from '../lib/api'
import { DataTable, type Column, type RowGroup } from './DataTable'

const num = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : v.toFixed(d))
const rate = (hz: number | null) => (hz === null ? '—' : hz >= 10 ? hz.toFixed(0) : hz.toFixed(2))
const CHECK_LABEL: Record<SimInputCheck['kind'], string> = { value: '값 충돌', rate: '주기', add: '그래프 누락', info: '참고' }

export function SimInputsView({ data, error, loading, selected, onSelect }: {
  data: SimInputs | null
  error?: string | null
  loading?: boolean
  selected: string | null
  onSelect: (nodeId: string) => void
}) {
  const groups = useMemo((): RowGroup<SimInputRow>[] => {
    const rows = data?.rows ?? []
    return [
      { id: 'frame', header: 'Frame 경로 · latency에 포함', rows: rows.filter((r) => r.cadence.path === 'frame') },
      { id: 'independent', header: '독립 cadence · frame 경로 밖 (latency 제외, 부하 · BW만)', rows: rows.filter((r) => r.cadence.path === 'independent') },
    ].filter((g) => g.rows.length)
  }, [data])
  if (error) return <div className="err" style={{ margin: 12 }}>{error}</div>
  if (loading || !data) return <div className="empty">Sim 입력 불러오는 중…</div>
  const checksOf = (id: string) => data.checks.filter((c) => c.node_id === id && c.kind !== 'info')
  const cols: Column<SimInputRow>[] = [
    { key: 'node', label: '요소', width: 130, sort: (r) => r.node_id, title: (r) => r.ip_ref ?? undefined,
      render: (r) => <span><b>{r.node_id}</b> <span className="faint">{r.kind.toUpperCase()}</span>{checksOf(r.node_id).length > 0 && <span className="badge v-warn" style={{ marginLeft: 4 }}>점검</span>}</span> },
    { key: 'rate', label: 'rate Hz', width: 64, align: 'right', sort: (r) => r.cadence.rate_hz, headTitle: 'frame 경로 = variant fps (SW는 sw_timing rate_hz / count_per_frame), 독립 = node_configs.timeline.period_ms',
      render: (r) => <span className="mono">{rate(r.cadence.rate_hz)}</span> },
    { key: 'pf', label: '회/frame', width: 66, align: 'right', sort: (r) => r.cadence.per_frame, render: (r) => <span className="mono">{num(r.cadence.per_frame, 2)}</span> },
    { key: 'dur', label: '실행 ms', width: 92, align: 'right', sort: (r) => r.duration?.mean_ms,
      title: (r) => (r.duration ? `${r.duration.basis}${r.duration.value_source ? ` · ${r.duration.value_source}` : ''}${r.duration.min_ms != null ? ` · ${r.duration.min_ms}–${r.duration.max_ms}` : ''}` : undefined),
      render: (r) => <span className="mono">{num(r.duration?.mean_ms, 2)}{r.duration?.p95_ms != null && <span className="faint"> · p95 {num(r.duration.p95_ms)}</span>}</span> },
    { key: 'load', label: 'sim 반영', width: 120, firstDir: -1, headTitle: 'SW: CPU ms/s = 실행 × rate · HW: duty % = 실행 × rate / 10',
      sort: (r) => r.load?.cpu_ms_per_s ?? r.load?.duty_pct,
      render: (r) => <span className="mono">{r.load?.cpu_ms_per_s !== undefined ? `CPU ${num(r.load.cpu_ms_per_s, 0)} ms/s` : r.load?.duty_pct !== undefined ? `duty ${num(r.load.duty_pct)} %` : '—'}</span> },
    { key: 'power', label: 'power mW', width: 92, align: 'right', firstDir: -1, sort: (r) => r.power?.mw,
      title: (r) => (r.power ? `${r.power.basis}${r.power.status ? ` · ${r.power.status}` : ''}` : undefined),
      render: (r) => (r.power?.mw != null ? <span className="mono">{num(r.power.mw)}</span> : r.power?.status ? <span className="faint">{r.power.status}</span> : <span className="faint">—</span>) },
    { key: 'bw', label: 'R / W MB/s', width: 100, align: 'right', firstDir: -1, sort: (r) => (r.bw_mbs ? r.bw_mbs.read + r.bw_mbs.write : null),
      render: (r) => <span className="mono">{r.bw_mbs ? `${num(r.bw_mbs.read)} / ${num(r.bw_mbs.write)}` : '—'}</span> },
    { key: 'src', label: '출처', width: 96, sort: (r) => r.duration?.value_source ?? r.duration?.basis,
      render: (r) => <span className="faint">{r.duration ? r.duration.value_source ?? r.duration.basis : '—'}</span> },
  ]
  return (
    <div className="sim-inputs">
      <div className="facet-row" style={{ gap: 6 }}>
        <span className="chip" title="SW node의 CPU ms/s 합 (그래프 안 SW만)">SW CPU {num(data.totals.sw_cpu_ms_per_s, 0)} ms/s</span>
        <span className="chip">독립 cadence {data.totals.independent_nodes}</span>
        <span className="chip" title="SW 실행 시간 case">timing {data.timing_case}</span>
        <span className="chip" title="HW 실행 시간 · power · BW 출처">{data.simulation_ref ? `sim ${data.simulation_ref}` : 'simulation evidence 없음'}</span>
        {data.measurement_ref && <span className="chip" title="SW 실측 비교 대상">실측 {data.measurement_ref}</span>}
      </div>
      <DataTable id="pipeline.sim-inputs" columns={cols} groups={groups} rowKey={(r) => r.node_id}
        rowClass={(r) => (r.node_id === selected ? 'sel' : '')} onRowClick={(r) => onSelect(r.node_id)} />
      {data.checks.length > 0 && <div className="sim-checks">
        <h5>점검</h5>
        {data.checks.map((c, i) => (
          <div key={i} className={`sim-check ${c.kind}`} onClick={() => c.node_id && onSelect(c.node_id)} role={c.node_id ? 'button' : undefined}>
            <span className={`badge ${c.kind === 'info' ? '' : 'v-warn'}`}>{CHECK_LABEL[c.kind]}</span> <b>{c.title}</b>
            <div className="faint">{c.detail}</div>
          </div>))}
      </div>}
    </div>
  )
}
