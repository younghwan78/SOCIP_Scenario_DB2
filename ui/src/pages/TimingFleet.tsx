import { useMemo, useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { fmt, nrtFactor, timingApi, verdictChip, type FleetRow, type Statistic } from '../lib/timingBudget'
import { Card, FleetRank } from '../components/TimingCharts'
import { DataTable, type Column } from '../components/DataTable'
import { SW_COLOR } from '../lib/timingBudget'

type Filter = 'all' | 'ok' | 'clock_up' | 'fail'

export function TimingFleetPage({ ctx }: { ctx: Ctx }) {
  const statistic = (ctx.params.stat === 'mean' ? 'mean' : 'max') as Statistic
  const q = useAsync(() => timingApi.fleet(ctx.scenario, { statistic, eis: 'auto', runtime_scale: 1 }), [ctx.scenario, statistic])
  const [filter, setFilter] = useState<Filter>('all')
  const [showAll, setShowAll] = useState(false)
  const rows = useMemo(() => q.data?.rows ?? [], [q.data])
  const shown = filter === 'all' ? rows : rows.filter((r) => r.verdict.status === filter)
  const counts = useMemo(() => {
    const c: Record<string, number> = { ok: 0, clock_up: 0, fail: 0 }
    rows.forEach((r) => { c[r.verdict.status] = (c[r.verdict.status] ?? 0) + 1 })
    return c
  }, [rows])
  const open = (v: string) => ctx.navigate('timing', { variant: v, stat: statistic === 'max' ? undefined : statistic })

  const cols: Column<FleetRow>[] = [
    { key: 'v', label: 'Variant', width: 220, sticky: true, sort: (r) => r.variant_id, render: (r) => <span className="mono">{r.variant_id.replace(/^cam-rec-/, '')}</span> },
    { key: 'fps', label: 'fps', width: 56, align: 'right', firstDir: -1, sort: (r) => r.fps, render: (r) => fmt(r.fps, 0) },
    { key: 'eis', label: 'EIS', width: 56, sort: (r) => (r.eis_on ? 1 : 0), render: (r) => (r.eis_on ? <span className="badge v-ok">ON</span> : <span className="faint">—</span>) },
    { key: 'rt', label: 'RT HW/예산 ms', width: 130, align: 'right', firstDir: -1, sort: (r) => r.stages.rt.hw_ms / r.stages.rt.budget_ms, render: (r) => <span className="mono" style={{ color: r.stages.rt.hw_ms > r.stages.rt.budget_ms ? 'var(--del-text)' : undefined }}>{fmt(r.stages.rt.hw_ms, 1)}/{fmt(r.stages.rt.budget_ms, 1)}</span> },
    { key: 'nrtsw', label: 'NRT SW ms', width: 150, firstDir: -1, sort: (r) => r.stages.nrt.sw_ms / r.period_ms, render: (r) => <MiniBar frac={r.stages.nrt.sw_ms / r.period_ms} text={`${fmt(r.stages.nrt.sw_ms, 1)} (${fmt((100 * r.stages.nrt.sw_ms) / r.period_ms, 0)}%)`} bad={!r.stages.nrt.feasible} /> },
    { key: 'postsw', label: 'Post SW ms', width: 104, align: 'right', firstDir: -1, sort: (r) => r.stages.post.sw_ms, render: (r) => fmt(r.stages.post.sw_ms, 1) },
    { key: 'nrtclk', label: 'NRT clock rule→set', width: 170, firstDir: -1, sort: (r) => nrtFactor(r), render: (r) => <span className="mono" title={r.clocks.nrt.ip ?? ''}>{fmt(r.clocks.nrt.rule_mhz, 0)}→{fmt(r.clocks.nrt.set_mhz, 0)}{r.clocks.nrt.level !== null ? ` L${r.clocks.nrt.level}` : ''} <span className="faint">×{fmt(nrtFactor(r), 2)}</span></span> },
    { key: 'post', label: 'GDC clock', width: 100, align: 'right', firstDir: -1, sort: (r) => r.clocks.post.set_mhz, render: (r) => fmt(r.clocks.post.set_mhz, 0) },
    { key: 'iv', label: '간격 P/V ms', width: 130, align: 'right', firstDir: -1, sort: (r) => Math.max(r.intervals.preview_max_ms ?? 0, r.intervals.video_max_ms ?? 0) / r.period_ms, render: (r) => <span className="mono" style={{ color: r.intervals.ok ? 'var(--primary-strong)' : 'var(--del-text)' }}>{fmt(r.intervals.preview_max_ms, 2)}/{fmt(r.intervals.video_max_ms, 2)}</span> },
    { key: 'lat', label: 'Latency P/V ms', width: 120, align: 'right', firstDir: -1, sort: (r) => r.latency.preview_ms, render: (r) => `${fmt(r.latency.preview_ms, 0)}/${fmt(r.latency.video_ms, 0)}` },
    { key: 'pw', label: 'Power mW', width: 160, firstDir: -1, sort: (r) => r.power.total_mw, render: (r) => <PowerMini r={r} /> },
    { key: 'cpu', label: 'CPU %', width: 70, align: 'right', firstDir: -1, sort: (r) => r.power.share_pct.cpu, render: (r) => fmt(r.power.share_pct.cpu, 0) },
    { key: 'bw', label: 'BW MB/s', width: 90, align: 'right', firstDir: -1, sort: (r) => r.bw.total_mbs, render: (r) => fmt(r.bw.total_mbs, 0) },
    { key: 'verdict', label: '판정', width: 110, sort: (r) => ({ fail: 0, clock_up: 1, ok: 2 }[r.verdict.status]), title: (r) => r.verdict.reasons.join('\n'), render: (r) => <span className={`badge ${verdictChip(r.verdict.status).cls}`}>{verdictChip(r.verdict.status).label}</span> },
  ]

  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ gap: 14, flexWrap: 'wrap' }}>
        <span className="muted" style={{ fontSize: 13 }}>SW 통계</span>
        <div className="seg" role="group" aria-label="SW 통계">
          {(['max', 'mean'] as const).map((s) => <button key={s} className={statistic === s ? 'on' : ''} onClick={() => ctx.navigate(undefined, { stat: s === 'max' ? undefined : s }, true)}>{s}</button>)}
        </div>
        <span className="muted" style={{ fontSize: 13 }}>판정</span>
        <div className="seg" role="group" aria-label="판정 필터">
          {(['all', 'fail', 'clock_up', 'ok'] as Filter[]).map((f) => <button key={f} className={filter === f ? 'on' : ''} onClick={() => setFilter(f)}>{f === 'all' ? `전체 ${rows.length}` : `${verdictChip(f).label} ${counts[f] ?? 0}`}</button>)}
        </div>
        <span className="grow" />
        {q.data && <span className="chip">DVFS {q.data.dvfs_table_ref ?? '미연결'}</span>}
      </div>
      {q.error && <div className="err">{q.error}</div>}
      {q.loading && <div className="empty">{ctx.scenario} 전체 variant 계산 중…</div>}
      {q.data && q.data.errors.length > 0 && <div className="err">{q.data.errors.length}개 variant 계산 실패: {q.data.errors.slice(0, 3).map((e) => e.variant_id).join(', ')}</div>}
      {q.data && <div className="tb-grid">
        <Card id="fleet-rank" title="NRT 필요 clock 배율 순위 (25% rule 대비)" note="행 = variant · 겹침 없음 · SW 비중 막대" defaultWide
          actions={<button className="btn tb-mini" onClick={() => setShowAll((s) => !s)}>{showAll ? '상위 25' : `전체 ${shown.length}`}</button>}>
          <FleetRank rows={shown} onPick={open} limit={showAll ? shown.length : 25} />
        </Card>
        <Card id="fleet-table" title="Scenario 표" note="header 클릭 = 정렬 · 행 클릭 = 상세" defaultWide minHeight={300}>
          <div className="table-x">
            <DataTable id="timing.fleet" columns={cols} rows={shown} rowKey={(r) => r.variant_id} onRowClick={(r) => open(r.variant_id)} defaultSort={{ key: 'nrtclk', dir: -1 }} />
          </div>
        </Card>
      </div>}
    </div>
  )
}

function MiniBar({ frac, text, bad }: { frac: number; text: string; bad: boolean }) {
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <svg width={60} height={10}><rect x={0} y={0} width={60} height={10} fill="#F7F4EF" /><rect x={0} y={0} width={Math.min(1, frac) * 60} height={10} fill={bad ? '#7F1D1D' : SW_COLOR} /></svg>
      <span className="mono">{text}</span>
    </span>
  )
}

function PowerMini({ r }: { r: FleetRow }) {
  const t = Math.max(r.power.total_mw, 1e-9)
  const w = 64
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 6 }} title={`CPU ${fmt(r.power.cpu_mw, 0)} · HW ${fmt(r.power.hw_mw, 0)} · BW ${fmt(r.power.bw_mw, 0)} mW`}>
      <svg width={w} height={10}>
        <rect x={0} y={0} width={(r.power.cpu_mw / t) * w} height={10} fill={SW_COLOR} />
        <rect x={(r.power.cpu_mw / t) * w} y={0} width={(r.power.hw_mw / t) * w} height={10} fill="#2F6F68" />
        <rect x={((r.power.cpu_mw + r.power.hw_mw) / t) * w} y={0} width={(r.power.bw_mw / t) * w} height={10} fill="#C2410C" />
      </svg>
      <span className="mono">{fmt(r.power.total_mw, 0)}</span>
    </span>
  )
}
