import { useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { fmt } from '../lib/timingBudget'
import { archApi, levels, short, type BoardRow, type HistoryRow } from '../lib/archExplore'
import { Card } from '../components/TimingCharts'
import { CompositionBars, RangeBoxes, SplitBar, SplitLegend, Waterfall } from '../components/ArchCharts'
import { DataTable, type Column } from '../components/DataTable'

export function PredictionsPage({ ctx }: { ctx: Ctx }) {
  const all = ctx.params.all === '1'
  const q = useAsync(() => archApi.board(all ? undefined : ctx.scenario), [ctx.scenario, all])
  const rows = q.data?.rows ?? []
  const sel = rows.find((r) => r.variant_id === ctx.params.v)
  const choose = (vid: string) => ctx.navigate(undefined, { v: vid === ctx.params.v ? undefined : vid }, true)
  const changed = rows.filter((r) => r.previous)
  const tot = rows.map((r) => r.power.total_mw)
  const cols: Column<BoardRow>[] = [
    { key: 'v', label: 'Variant', width: 210, sticky: true, sort: (r) => r.variant_id, render: (r) => <span className="mono">{short(r.variant_id)}</span> },
    ...(all ? [{ key: 's', label: 'Scenario', width: 170, sort: (r: BoardRow) => r.scenario_id, render: (r: BoardRow) => <span className="mono faint">{r.scenario_id}</span> }] : []),
    { key: 'fps', label: 'fps', width: 52, align: 'right', firstDir: -1, sort: (r) => r.fps, render: (r) => fmt(r.fps, 0) },
    { key: 'tot', label: 'Power mW', width: 160, align: 'right', firstDir: -1, sort: (r) => r.power.total_mw, render: (r) => <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><SplitBar p={r.power} width={70} /><b className="mono">{fmt(r.power.total_mw, 1)}</b></span> },
    { key: 'cpu', label: 'CPU', width: 62, align: 'right', firstDir: -1, sort: (r) => r.power.cpu_mw, render: (r) => fmt(r.power.cpu_mw, 0) },
    { key: 'hw', label: 'HW', width: 62, align: 'right', firstDir: -1, sort: (r) => r.power.hw_mw, render: (r) => fmt(r.power.hw_mw, 0) },
    { key: 'bwip', label: 'IP DMA', width: 70, align: 'right', firstDir: -1, sort: (r) => r.power.bw_ip_mw ?? r.power.bw_mw, render: (r) => fmt(r.power.bw_ip_mw ?? r.power.bw_mw, 0) },
    { key: 'bwcpu', label: 'CPU DMA', width: 74, align: 'right', firstDir: -1, sort: (r) => r.power.bw_cpu_mw ?? -1, render: (r) => fmt(r.power.bw_cpu_mw, 1) },
    { key: 'bw', label: 'BW MB/s', width: 84, align: 'right', firstDir: -1, sort: (r) => r.bw_mbs, render: (r) => fmt(r.bw_mbs, 0) },
    { key: 'd', label: 'Δ 직전', width: 90, align: 'right', firstDir: -1, sort: (r) => Math.abs(r.previous?.delta_mw ?? 0), render: (r) => r.previous ? <span className="mono" style={{ color: r.previous.delta_mw > 0 ? 'var(--del-text)' : 'var(--primary-strong)' }}>{r.previous.delta_mw >= 0 ? '+' : ''}{fmt(r.previous.delta_mw, 1)}</span> : <span className="faint">첫 등록</span> },
    { key: 'range', label: 'range mW', width: 100, align: 'right', firstDir: -1, sort: (r) => (r.distribution ? r.distribution.total_mw.max - r.distribution.total_mw.min : 0), render: (r) => r.distribution ? <span className="mono">{fmt(r.distribution.total_mw.min, 0)}–{fmt(r.distribution.total_mw.max, 0)}</span> : '—' },
    { key: 'src', label: '출처 · 선택 규칙 · 대안', width: 300, sort: (r) => r.run_created_at ?? '', title: (r) => `${r.run_id}\n${r.case_key}${r.reason ? `\n사유: ${r.reason}` : ''}`, render: (r) => <span style={{ fontSize: 12 }}><span className="mono">{r.run_title ?? r.run_id}</span> · <span className={`badge ${r.selected_by === 'user' ? 'v-warn' : 'v-ok'}`}>{r.selection_rule}</span> · <span className="faint">1/{r.eligible_cases?.toLocaleString()}</span></span> },
    { key: 'sw', label: 'SW 기준', width: 86, sort: (r) => `${r.statistic}${r.runtime_scale}`, render: (r) => <span className="mono faint">{r.statistic} ×{r.runtime_scale}</span> },
    { key: 'comp', label: 'Comp', width: 56, align: 'right', firstDir: -1, sort: (r) => r.compression.length, title: (r) => r.compression.join(', '), render: (r) => r.compression.length },
    { key: 'dvfs', label: 'DVFS', width: 160, sort: (r) => levels(r.dvfs), render: (r) => <span className="mono faint">{levels(r.dvfs)}</span> },
    { key: 'ver', label: '검증', width: 64, align: 'right', sort: (r) => Math.abs(r.verified?.delta_pct ?? 99), render: (r) => (r.verified ? <span style={{ color: r.verified.ok ? 'var(--primary-strong)' : 'var(--del-text)' }}>{r.verified.ok ? '✓' : '✗'}</span> : '—') },
    { key: 'at', label: '등록', width: 120, firstDir: -1, sort: (r) => r.created_at ?? '', render: (r) => <span className="mono faint">{r.created_at?.slice(0, 16).replace('T', ' ')}</span> },
  ]
  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ gap: 12, flexWrap: 'wrap' }}>
        <div className="seg sm" role="group" aria-label="범위">
          <button className={!all ? 'on' : ''} onClick={() => ctx.navigate(undefined, { all: undefined, v: undefined }, true)}>현재 scenario</button>
          <button className={all ? 'on' : ''} onClick={() => ctx.navigate(undefined, { all: '1', v: undefined }, true)}>전체</button>
        </div>
        <span className="faint" style={{ fontSize: 12 }}>current 예측은 조합 탐색에서만 등록됩니다 (기본 = 최저 power 조합).</span>
        <span className="grow" />
        <a className="btn" href="#/explore">조합 탐색 →</a>
      </div>
      {q.error && <div className="err">{q.error}</div>}
      {q.loading && <div className="empty">불러오는 중…</div>}
      {q.data && !rows.length && <div className="empty">등록된 예측이 없습니다. 조합 탐색에서 “최저 power 조합 전체 등록”을 실행하세요.</div>}
      {rows.length > 0 && <>
        <section className="tb-kpis">
          {[['current 예측', `${rows.length}`, all ? '전체 scenario' : ctx.scenario],
            ['Power 범위', `${fmt(Math.min(...tot), 0)}–${fmt(Math.max(...tot), 0)}`, 'mW (등록 조합)'],
            ['직전 대비 변경', `${changed.length}`, changed.length ? `평균 ${fmt(changed.reduce((s, r) => s + (r.previous?.delta_mw ?? 0), 0) / changed.length, 1)} mW` : '—'],
            ['사람 선택', `${rows.filter((r) => r.selected_by === 'user').length}`, '추천 외 조합 (사유 기록)']].map(([l, v, n]) =>
            <div key={l} className="panel tb-kpi"><div className="faint" style={{ fontSize: 12 }}>{l}</div><div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{v}</div><div className="faint" style={{ fontSize: 11 }}>{n}</div></div>)}
        </section>
        <div className="tb-grid">
          {sel && <ChangeCard key={sel.id} row={sel} />}
          <Card id="pr-table" title="예측 현황 (current)" note="header 클릭 = 정렬 · 행 클릭 = 변경 원인" defaultWide minHeight={260}>
            <SplitLegend />
            <div className="table-scroll" style={{ maxHeight: 560 }}>
              <DataTable id="arch.board" columns={cols} rows={rows} rowKey={(r) => r.id} onRowClick={(r) => choose(r.variant_id)} defaultSort={{ key: 'tot', dir: -1 }}
                rowClass={(r) => (r.variant_id === ctx.params.v ? 'selected' : '')} />
            </div>
          </Card>
          <Card id="pr-range" title="등록 예측 vs 탐색 range" note="◆ 등록 · ○ 직전 등록 · box = 조합 × SW 통계" defaultWide>
            <RangeBoxes unit="mW" selected={ctx.params.v} onPick={choose}
              rows={rows.map((r) => ({ id: r.variant_id, label: short(r.variant_id), dist: r.distribution?.total_mw, ok: true, marker: r.power.total_mw, base: r.previous?.total_mw ?? null }))} />
          </Card>
          <Card id="pr-comp" title="등록 예측 Power 구성" note="CPU · CPU DMA · IP · IP DMA (mW)" defaultWide>
            <CompositionBars selected={ctx.params.v} onPick={choose} rows={rows.map((r) => ({ id: r.variant_id, label: short(r.variant_id), p: r.power }))} />
          </Card>
        </div>
      </>}
    </div>
  )
}

function ChangeCard({ row }: { row: BoardRow }) {
  const h = useAsync(() => archApi.history(row.scenario_id, row.variant_id), [row.id])
  const [oldId, setOldId] = useState<string | undefined>(row.previous?.id)
  const c = useAsync(() => (oldId ? archApi.compare({ old_id: oldId, new_id: row.id }) : Promise.resolve(null)), [oldId, row.id])
  const a = c.data?.attribution
  return <>
    <Card id="pr-change" title={`${short(row.variant_id)} — 변경 원인`} note="CPU(SW) · IP workload/DVFS 전압(LMDI) · DMA traffic · compression" defaultWide>
      {!oldId && <div className="empty">비교할 이전 등록이 없습니다 (첫 등록).</div>}
      {c.error && <div className="err">{c.error}</div>}
      {a && <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,2fr) minmax(240px,1fr)', gap: 16 }}>
        <Waterfall a={a} />
        <div style={{ display: 'grid', gap: 8, alignContent: 'start', fontSize: 13 }}>
          <div><span className="mono" style={{ fontSize: 20, fontWeight: 600, color: a.delta_mw > 0 ? 'var(--del-text)' : 'var(--primary-strong)' }}>{a.delta_mw >= 0 ? '+' : ''}{fmt(a.delta_mw, 1)} mW</span> <span className="faint">({fmt(a.delta_pct, 1)}%)</span></div>
          <div className="faint">CPU {fmt(a.components.cpu_mw, 1)} · IP {fmt(a.components.hw_mw, 1)} · BW {fmt(a.components.bw_mw, 1)}{a.components.bw_ip_mw !== undefined ? ` (IP DMA ${fmt(a.components.bw_ip_mw, 1)} · CPU DMA ${fmt(a.components.bw_cpu_mw, 1)})` : ''} mW</div>
          <table className="tb-mini-table"><thead><tr><th>원인</th><th>ΔmW</th></tr></thead>
            <tbody>{Object.entries(a.by_category).map(([k, v]) => <tr key={k}><td>{k}</td><td className="mono">{v >= 0 ? '+' : ''}{fmt(v, 1)}</td></tr>)}</tbody></table>
          <table className="tb-mini-table"><thead><tr><th>입력 변경</th><th>이전 → 현재</th></tr></thead>
            <tbody>{a.context_changes.map((x) => <tr key={x.item}><td>{x.item}</td><td className="mono" style={{ fontSize: 11 }}>{show(x.old)} → {show(x.new)}</td></tr>)}</tbody></table>
        </div>
      </div>}
    </Card>
    <Card id="pr-history" title="등록 이력" note="행 선택 = 비교 기준(이전)">
      <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th /><th>등록</th><th>상태</th><th>Power mW</th><th>규칙</th><th>run</th></tr></thead>
        <tbody>{(h.data ?? []).map((x: HistoryRow) => (
          <tr key={x.id} className={x.id === oldId ? 'selected' : ''} onClick={() => x.id !== row.id && setOldId(x.id)} style={{ cursor: x.id === row.id ? 'default' : 'pointer' }}>
            <td>{x.id !== row.id && <input type="radio" checked={x.id === oldId} onChange={() => setOldId(x.id)} aria-label="비교 기준" />}</td>
            <td className="mono faint">{x.created_at?.slice(0, 16).replace('T', ' ')}</td>
            <td><span className={`badge ${x.status === 'current' ? 'v-ok' : ''}`}>{x.status}</span></td>
            <td className="mono">{fmt(x.total_mw, 1)}</td><td title={x.reason ?? ''}>{x.selection_rule}</td><td className="mono faint" style={{ fontSize: 11 }}>{x.run_id}</td>
          </tr>))}</tbody>
      </table>
    </Card>
  </>
}

function show(v: unknown): string {
  if (Array.isArray(v)) return v.length ? v.join(', ') : '—'
  if (v === null || v === undefined) return '—'
  return String(v)
}
