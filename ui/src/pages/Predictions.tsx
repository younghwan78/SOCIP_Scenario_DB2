import { useMemo, useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { api } from '../lib/api'
import { fmt } from '../lib/timingBudget'
import { archApi, conditionParams, conditionText, levels, short, variantKey, type BoardRow, type HistoryRow } from '../lib/archExplore'
import { Card } from '../components/TimingCharts'
import { CompositionBars, RangeBoxes, SplitBar, SplitLegend, Waterfall } from '../components/ArchCharts'
import { DataTable, type Column } from '../components/DataTable'
import { OPTION_NOTE, OptionResults, OptionReviewPanel, ReviewBadge, signed } from '../components/PowerOptions'
import { ProvBadge } from '../components/Provenance'
import { powerScope, type Prov } from '../lib/provenance'
import { KIND_LABEL, RISK_CLASS, RISK_LABEL, assessAll, type RiskLevel, type RiskRow } from '../lib/predRisk'
import { calibrationApi } from '../lib/calibration'
import { batteryNote, maText, useBattery, type Battery } from '../lib/battery'
import { usePref } from '../components/Layout'
import { JUDGE_CLASS, JUDGE_LABEL, reviewApi, useReferences, type References } from '../lib/review'
import { ThermalWatchView } from '../components/ThermalWatch'
import { useSimProfiles } from '../lib/simProfile'
import type { Ctx as AppCtx } from '../App'
import { RecomputePanel } from '../components/RecomputePanel'

const regProv = (r: BoardRow): Prov => ({
  kind: 'registered', engine: r.condition?.source === 'timing-budget' ? 'Timing Budget 조건' : 'Arch exploration', scope: powerScope({ cpu: r.power.cpu_mw, hw: r.power.hw_mw, bw: r.power.bw_mw }),
  id: r.id, at: r.created_at, notes: [`run: ${r.run_title ?? r.run_id}`, `선택: ${r.selection_rule} · SW ${r.statistic} ×${r.runtime_scale}`],
})

export function PredictionsPage({ ctx }: { ctx: Ctx }) {
  // scope = the selected 과제; the in-page filter narrows it to one scenario (sf), independent of the global picker
  const sf = ctx.params.sf ?? ''
  const all = !sf
  const [tick, setTick] = useState(0)
  const q = useAsync(() => archApi.board(undefined, ctx.project || undefined), [ctx.project, tick])
  const allRows = q.data?.rows ?? []
  const ppQ = useAsync(() => (ctx.params.rc ? calibrationApi.powerParams().catch(() => []) : Promise.resolve([])), [ctx.params.rc])
  const rows = sf ? allRows.filter((r) => r.scenario_id === sf) : allRows
  const battery = useBattery(ctx.project, ctx.params.cfg)
  // customer performance / thermal target: URL (shareable) > this viewer's last value
  const [targetPref, setTargetPref] = usePref<string>('pred.target_mw', '')
  const targetRaw = ctx.params.target ?? targetPref
  const target = Number(targetRaw) > 0 ? Number(targetRaw) : null
  const scenIds = [...new Set(rows.map((r) => r.scenario_id))].sort()
  const covQ = useAsync(() => Promise.all(scenIds.map((sid) => calibrationApi.coverage(sid).then((c) => [sid, c] as const).catch(() => null)))
    .then((list) => { const m = new Map<string, number>(); let ok = false
      for (const x of list) { if (!x) continue; ok = true; for (const [vid, c] of Object.entries(x[1])) m.set(`${x[0]}|${vid}`, c.measurement) }
      return ok ? m : undefined }), [scenIds.join(',')])
  const refs = useReferences(ctx.project)
  const simRef = useSimProfiles(ctx.project, ctx.params.cfg)
  // PRED-04: is each registration still today's result?  PRED-05: evaluation targets without a registration
  const freshQ = useAsync(() => (allRows.length ? archApi.freshness(undefined, ctx.project || undefined).catch(() => null) : Promise.resolve(null)), [allRows.length, ctx.project, tick])
  const stale = useMemo(() => new Map((freshQ.data?.rows ?? []).filter((x) => x.status === 'stale').map((x) => [x.prediction_id, x.reasons])), [freshQ.data])
  const scopeScenarios = sf ? [sf] : (ctx.catalog ?? []).map((c) => c.scenario_id)
  const scnCount = useMemo(() => { const m = new Map<string, number>(); for (const r of allRows) m.set(r.scenario_id, (m.get(r.scenario_id) ?? 0) + 1); return m }, [allRows])
  const scnName = (sid: string) => (ctx.catalog ?? []).find((c) => c.scenario_id === sid)?.scenario_name ?? sid
  const varsQ = useAsync(() => Promise.all(scopeScenarios.map((sid) => api.variants(sid).then((r) => r.items.filter((v) => !v.derived_from_variant).map((v) => [sid, v.id] as const)).catch(() => [] as (readonly [string, string])[]))).then((x) => x.flat()), [scopeScenarios.join(',')])
  const registered = new Set(rows.map((r) => `${r.scenario_id}|${r.variant_id}`))
  const unregistered = (varsQ.data ?? []).filter(([sid, vid]) => !registered.has(`${sid}|${vid}`))
  const risk = assessAll(rows, { target_mw: target, measured: covQ.data ?? undefined, references: refs?.references,
    tolerance_pct: refs?.tolerance_pct, max_latency_frames: refs?.policy.max_latency_frames, stale })
  const watch = (refs?.policy.thermal_watch.length ?? 0) > 0
  const twQ = useAsync(() => (watch && ctx.project ? reviewApi.thermalWatch(ctx.project, simRef.ref) : Promise.resolve(null)), [watch, ctx.project, simRef.ref, tick])
  const staleRows = rows.filter((r) => r.throughput_model === 'stage' && refs?.policy.throughput_model === 'pipelined').length
  const sel = rows.find((r) => r.id === ctx.params.v)
  const choose = (vid: string) => ctx.navigate(undefined, { v: vid === ctx.params.v ? undefined : vid }, true)
  const changed = rows.filter((r) => r.previous)
  const tot = rows.map((r) => r.power.total_mw)
  const withOpt = rows.filter((r) => r.power_options?.best)
  const optBest = withOpt.map((r) => r.power_options?.best?.delta_mw ?? 0)
  // U3: one banner instead of the same text on every row
  const notExplored = rows.filter((r) => !r.power_options || r.power_options.status === 'not_explored').length
  const firstReg = rows.length - changed.length
  const cols: Column<BoardRow>[] = [
    { key: 'v', label: 'Variant', width: 210, sticky: true, sort: (r) => r.variant_id, render: (r) => <span className="mono">{short(r.variant_id)}</span> },
    ...(all ? [{ key: 's', label: 'Scenario', width: 170, sort: (r: BoardRow) => r.scenario_id, render: (r: BoardRow) => <span className="mono faint">{r.scenario_id}</span> }] : []),
    { key: 'fps', label: 'fps', width: 52, align: 'right', firstDir: -1, sort: (r) => r.fps, render: (r) => fmt(r.fps, 0) },
    { key: 'risk', label: 'Risk', width: 70, firstDir: -1, sort: (r) => { const x = risk.find((y) => y.row.id === r.id); return x ? ({ high: 3, med: 2, low: 1, ok: 0 } as Record<RiskLevel, number>)[x.level] * 100 + x.score : 0 },
      title: (r) => risk.find((y) => y.row.id === r.id)?.risks.map((x) => `[${KIND_LABEL[x.kind]}] ${x.text}`).join('\n') ?? '',
      render: (r) => { const x = risk.find((y) => y.row.id === r.id); return x ? <span className={`badge ${RISK_CLASS[x.level]}`}>{RISK_LABEL[x.level]}</span> : null } },
    { key: 'tot', label: 'Power mW', width: 200, align: 'right', firstDir: -1, sort: (r) => r.power.total_mw, render: (r) => <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><SplitBar p={r.power} width={70} /><b className="mono">{fmt(r.power.total_mw, 1)}</b><span className="mono faint" style={{ fontSize: 11 }} title={batteryNote(battery)}>{maText(r.power.total_mw, battery)}</span><ProvBadge prov={regProv(r)} compact /></span> },
    { key: 'cpu', label: 'CPU', width: 62, align: 'right', firstDir: -1, sort: (r) => r.power.cpu_mw, render: (r) => fmt(r.power.cpu_mw, 0) },
    { key: 'hw', label: 'HW', width: 62, align: 'right', firstDir: -1, sort: (r) => r.power.hw_mw, render: (r) => fmt(r.power.hw_mw, 0) },
    { key: 'bwip', label: 'IP BW', width: 70, align: 'right', firstDir: -1, sort: (r) => r.power.bw_ip_mw ?? r.power.bw_mw, render: (r) => fmt(r.power.bw_ip_mw ?? r.power.bw_mw, 0) },
    { key: 'bwcpu', label: 'CPU BW', width: 74, align: 'right', firstDir: -1, sort: (r) => r.power.bw_cpu_mw ?? -1, render: (r) => fmt(r.power.bw_cpu_mw, 1) },
    { key: 'bw', label: 'BW MB/s', width: 84, align: 'right', firstDir: -1, sort: (r) => r.bw_mbs, render: (r) => fmt(r.bw_mbs, 0) },
    { key: 'd', label: 'Δ 직전', width: 90, align: 'right', firstDir: -1, sort: (r) => Math.abs(r.previous?.delta_mw ?? 0), render: (r) => r.previous ? <span className="mono" style={{ color: r.previous.delta_mw > 0 ? 'var(--del-text)' : 'var(--primary-strong)' }}>{r.previous.delta_mw >= 0 ? '+' : ''}{fmt(r.previous.delta_mw, 1)}</span> : <span className="faint" title="직전 등록 예측 없음 (첫 등록)">—</span> },
    { key: 'opt', label: '절감 option (IQ)', width: 190, align: 'right', firstDir: 1, sort: (r) => r.power_options?.best?.delta_mw ?? 0,
      title: (r) => r.power_options?.best ? `${r.power_options.best.labels.join(' + ')}\n${r.power_options.results.length}개 조합 · ${OPTION_NOTE}` : (r.power_options?.notes ?? []).join('\n'),
      render: (r) => { const po = r.power_options; const b = po?.best
        if (b) return <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><b className="mono" style={{ color: 'var(--primary-strong)' }}>{signed(b.delta_mw)}</b><span className="faint mono" style={{ fontSize: 11 }}>{signed(b.delta_pct)}%</span><ReviewBadge status={b.review_status} /></span>
        if (!po || po.status === 'not_explored') return <span className="faint" title="power option 미탐색 — 상단 안내 참고">·</span>
        return <span className="faint">—</span> } },
    { key: 'range', label: 'range mW', width: 100, align: 'right', firstDir: -1, sort: (r) => (r.distribution ? r.distribution.total_mw.max - r.distribution.total_mw.min : 0), render: (r) => r.distribution ? <span className="mono">{fmt(r.distribution.total_mw.min, 0)}–{fmt(r.distribution.total_mw.max, 0)}</span> : '—' },
    { key: 'src', label: '출처 · 선택 규칙 · 대안', width: 300, sort: (r) => r.run_created_at ?? '', title: (r) => `${r.run_id}\n${r.case_key}${r.reason ? `\n사유: ${r.reason}` : ''}`, render: (r) => <span style={{ fontSize: 12 }}><span className="mono">{r.run_title ?? r.run_id}</span> · <span className={`badge ${r.selected_by === 'user' ? 'v-warn' : 'v-ok'}`}>{r.selection_rule}</span> · <span className="faint">1/{r.eligible_cases?.toLocaleString()}</span></span> },
    { key: 'cond', label: '조건', width: 250, sort: (r) => conditionText(r.condition), title: (r) => `${conditionText(r.condition)}${r.condition?.config_profile_ref ? `\nprofile ${r.condition.config_profile_ref}` : ''}\n클릭 = ${r.condition?.applied_options?.length ? '적용 option이 저장된 조합 탐색' : 'Timing Budget'}에서 열기`,
      render: (r) => <a href="#" style={{ fontSize: 12 }} onClick={(e) => { e.preventDefault(); e.stopPropagation(); if (r.condition?.applied_options?.length) ctx.navigate('explore', { run: r.run_id, v: variantKey(r) }); else ctx.navigate('timing', conditionParams(r)) }}>
        <span className="mono faint">{conditionText(r.condition)}</span> <span>→</span></a> },
    { key: 'comp', label: 'Comp', width: 56, align: 'right', firstDir: -1, sort: (r) => r.compression.length, title: (r) => r.compression.join(', '), render: (r) => r.compression.length },
    { key: 'dvfs', label: 'DVFS', width: 160, sort: (r) => levels(r.dvfs), render: (r) => <span className="mono faint">{levels(r.dvfs)}</span> },
    { key: 'ver', label: '검증', width: 64, align: 'right', sort: (r) => Math.abs(r.verified?.delta_pct ?? 99), render: (r) => (r.verified ? <span style={{ color: r.verified.ok ? 'var(--primary-strong)' : 'var(--del-text)' }}>{r.verified.ok ? '✓' : '✗'}</span> : '—') },
    { key: 'at', label: '등록', width: 120, firstDir: -1, sort: (r) => r.created_at ?? '', render: (r) => <span className="mono faint">{r.created_at?.slice(0, 16).replace('T', ' ')}</span> },
  ]
  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ gap: 12, flexWrap: 'wrap' }}>
        <label className="faint" style={{ fontSize: 12, display: 'inline-flex', gap: 6, alignItems: 'center' }} title="과제 전체 등록 예측 중 scenario 하나로 좁히기 (상단 Ctrl K 선택과 무관)">Scenario
          <select value={sf} onChange={(e) => ctx.navigate(undefined, { sf: e.target.value || undefined, v: undefined, all: undefined }, true)} aria-label="scenario filter">
            <option value="">과제 전체 ({allRows.length})</option>
            {[...new Set([...(ctx.catalog ?? []).map((c) => c.scenario_id), ...scnCount.keys()])].map((sid) => <option key={sid} value={sid}>{scnName(sid)} ({scnCount.get(sid) ?? 0})</option>)}
          </select></label>
        <label className="faint" style={{ fontSize: 12, display: 'inline-flex', gap: 6, alignItems: 'center' }} title="고객 성능·발열 scenario의 power 목표 (모든 행에 같은 값). 비우면 상대 비교만. URL에 남아 공유 가능">
          {refs?.policy.power_reference ? '목표 (전과제 값 없는 variant)' : '목표 power'} <input className="input" type="number" min={0} step={10} style={{ width: 80, padding: '3px 6px' }} value={targetRaw} placeholder="mW"
            onChange={(e) => { setTargetPref(e.target.value); ctx.navigate(undefined, { target: e.target.value || undefined }, true) }} /> mW
          {target && <span className="mono">({maText(target, battery)}@Vbat)</span>}</label>
        <span className="faint" style={{ fontSize: 12 }}>등록: Timing Budget (variant 하나 · 조건 지정) 또는 조합 탐색 (일괄 · 최저 power 조합). 조건 열 클릭 = 그 조건으로 Timing Budget 열기.</span>
        <span className="grow" />
        <button className="btn" onClick={() => ctx.navigate(undefined, { rc: ctx.params.rc ? undefined : '1' }, true)}
          title="등록 조건 그대로(또는 새 power params로) 다시 계산해 재등록 — 입력 변경(stale) 예측 정리 · 보정 params 반영">재계산…</button>
        <a className="btn" href="#/explore">조합 탐색 →</a>
      </div>
      {ctx.params.rc && <RecomputePanel key={`${ctx.project}:${sf ?? ''}:${ctx.params.pp ?? ''}`} rows={rows} staleIds={new Set(stale.keys())} params={ppQ.data ?? []} initialParams={ctx.params.pp}
        onDone={() => setTick((t) => t + 1)} onClose={() => ctx.navigate(undefined, { rc: undefined, pp: undefined }, true)} />}
      {q.error && <div className="err">{q.error}</div>}
      {q.loading && <div className="empty">불러오는 중…</div>}
      {q.data && !rows.length && <div className="empty">등록된 예측이 없습니다. Timing Budget에서 조건을 정해 “예측으로 등록”하거나 조합 탐색에서 “최저 power 조합 전체 등록”을 실행하세요.</div>}
      {rows.length > 0 && (notExplored > 0 || firstReg === rows.length) && <div className="lib-note warn">
        {notExplored > 0 && <>등록 예측 {rows.length}건 중 <b>{notExplored}건</b>은 power option(bcrop · L0 skip · IP mode)을 탐색하지 않은 run에서 등록됐습니다. 조합 탐색에서 “Power option”을 켜고 다시 실행하면 절감 후보가 채워집니다. </>}
        {firstReg === rows.length && <>모두 첫 등록이라 직전 대비 변경 원인(Δ 직전)은 아직 없습니다.</>}
        {' '}<a href="#/explore">조합 탐색 →</a>
      </div>}
      {rows.length > 0 && <>
        <section className="tb-kpis">
          {[['current 예측', `${rows.length}`, all ? '과제 전체 scenario' : scnName(sf)],
            ['Power 범위', `${fmt(Math.min(...tot), 0)}–${fmt(Math.max(...tot), 0)}`, 'mW (등록 조합)'],
            ['직전 대비 변경', `${changed.length}`, changed.length ? `평균 ${fmt(changed.reduce((s, r) => s + (r.previous?.delta_mw ?? 0), 0) / changed.length, 1)} mW` : '—'],
            ['사람 선택', `${rows.filter((r) => r.selected_by === 'user').length}`, '추천 외 조합 (사유 기록)'],
            ['Power option', `${withOpt.length}`, withOpt.length ? `최대 절감 ${fmt(Math.min(...optBest), 1)} ~ ${fmt(Math.max(...optBest), 1)} mW · IQ 평가 대상` : 'variant 아님 · IQ 평가 대상']].map(([l, v, n]) =>
            <div key={l} className="panel tb-kpi"><div className="faint" style={{ fontSize: 12 }}>{l}</div><div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{v}</div><div className="faint" style={{ fontSize: 11 }}>{n}</div></div>)}
        </section>
        <div className="tb-grid">
          {sel && <ChangeCard key={sel.id} row={sel} />}
          {sel && <OptionsCard key={`o-${sel.id}`} row={sel} onChanged={() => setTick((t) => t + 1)} />}
          <RiskCard risk={risk} target={target} battery={battery} ctx={ctx} measuredKnown={!!covQ.data} onPick={choose} refs={refs} staleRows={staleRows}
            coverage={{ targets: varsQ.data?.length ?? null, unregistered, stale: stale.size, freshChecked: !!freshQ.data }} />
          {watch && <Card id="pr-thermal" title="② 발열 대응 — power 감소 요청 대비 (thermal watch)" defaultWide minHeight={160}
            note="고객 board 발열로 power 감소 요청이 오는 scenario · 기준 = 화질·fps 유지 최적 · lever별 절감 mW/mA와 희생 · −10/−20% 요청 충족 여부">
            {twQ.error ? <div className="err">{twQ.error}</div> : !twQ.data ? <div className="empty">계산 중… (IP clock level what-if 포함)</div>
              : <ThermalWatchView data={twQ.data} battery={battery} onOpen={(sc, v) => ctx.navigate('timing', { scenario: sc, variant: v })} />}
          </Card>}
          <Card id="pr-table" title="예측 현황 (current)" note="header 클릭 = 정렬 · 행 클릭 = 변경 원인" defaultWide minHeight={260}>
            <SplitLegend />
            <div className="table-x">
              <DataTable id="arch.board" columns={cols} rows={rows} rowKey={(r) => r.id} onRowClick={(r) => choose(r.id)} defaultSort={{ key: 'tot', dir: -1 }}
                rowClass={(r) => (r.id === ctx.params.v ? 'selected' : '')} />
            </div>
          </Card>
          <Card id="pr-range" title="등록 예측 vs 탐색 range" note="◆ 등록 · ○ 직전 등록 · box = 조합 × SW 통계" defaultWide>
            <RangeBoxes unit="mW" selected={ctx.params.v} onPick={choose}
              rows={rows.map((r) => ({ id: r.id, label: short(r.variant_id), dist: r.distribution?.total_mw, ok: true, marker: r.power.total_mw, base: r.previous?.total_mw ?? null }))} />
          </Card>
          <Card id="pr-comp" title="등록 예측 Power 구성" note="CPU · CPU BW · IP · IP BW (mW)" defaultWide>
            <CompositionBars selected={ctx.params.v} onPick={choose} rows={rows.map((r) => ({ id: r.id, label: short(r.variant_id), p: r.power }))} />
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
    <Card id="pr-change" title={`${short(row.variant_id)} — 변경 원인`} note="CPU(SW) · IP workload/DVFS 전압(LMDI) · BW traffic · compression" defaultWide>
      {!oldId && <div className="empty">비교할 이전 등록이 없습니다 (첫 등록).</div>}
      {c.error && <div className="err">{c.error}</div>}
      {a && <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,2fr) minmax(240px,1fr)', gap: 16 }}>
        <Waterfall a={a} />
        <div style={{ display: 'grid', gap: 8, alignContent: 'start', fontSize: 13 }}>
          <div><span className="mono" style={{ fontSize: 20, fontWeight: 600, color: a.delta_mw > 0 ? 'var(--del-text)' : 'var(--primary-strong)' }}>{a.delta_mw >= 0 ? '+' : ''}{fmt(a.delta_mw, 1)} mW</span> <span className="faint">({fmt(a.delta_pct, 1)}%)</span></div>
          <div className="faint">CPU {fmt(a.components.cpu_mw, 1)} · IP {fmt(a.components.hw_mw, 1)} · BW {fmt(a.components.bw_mw, 1)}{a.components.bw_ip_mw !== undefined ? ` (IP BW ${fmt(a.components.bw_ip_mw, 1)} · CPU BW ${fmt(a.components.bw_cpu_mw, 1)})` : ''} mW</div>
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

function OptionsCard({ row, onChanged }: { row: BoardRow; onChanged: () => void }) {
  const po = row.power_options
  return (
    <Card id="pr-options" title={`${short(row.variant_id)} — Power option (IQ 평가 대상)`} note={OPTION_NOTE} defaultWide>
      {(!po || po.status === 'not_explored') && <div className="empty">이 예측은 power option 탐색 전에 등록됐습니다. 조합 탐색을 다시 실행해 등록하세요.</div>}
      {po && po.status !== 'not_explored' && <div style={{ display: 'grid', gap: 12 }}>
        {po.reference?.note && <div className="faint" style={{ fontSize: 12 }}>⚠ {po.reference.note}</div>}
        {po.notes.length > 0 && <ul className="faint" style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>{po.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
        {po.status === 'none' && <div className="empty">적용 가능한 option이 없습니다 (knobs.yaml explore / IP sim.modes substitutes 선언 필요).</div>}
        {po.results.length > 0 && <OptionResults results={po.results} best={po.best?.key} />}
        <OptionReviewPanel row={row} onChanged={onChanged} />
      </div>}
    </Card>
  )
}

function show(v: unknown): string {
  if (Array.isArray(v)) return v.length ? v.join(', ') : '—'
  if (v === null || v === undefined) return '—'
  return String(v)
}

const LEVELS: RiskLevel[] = ['high', 'med', 'low', 'ok']

/** Risk · Focus: which predictions threaten the customer's performance / thermal target and what to work on. */
function RiskCard({ risk, target, battery, ctx, measuredKnown, onPick, refs, staleRows, coverage }: { risk: RiskRow[]; target: number | null; battery: Battery; ctx: AppCtx; measuredKnown: boolean; onPick: (id: string) => void
  refs: References | null; staleRows: number
  coverage: { targets: number | null; unregistered: (readonly [string, string])[]; stale: number; freshChecked: boolean } }) {
  const pr = refs?.policy.power_reference
  const [showAll, setShowAll] = useState(false)
  const count = (l: RiskLevel) => risk.filter((x) => x.level === l).length
  const listed = risk.filter((x) => x.level !== 'ok').concat(risk.filter((x) => x.level === 'ok').slice(0, 3))
  const shown = showAll ? listed : listed.slice(0, 10)
  const over = risk.filter((x) => (x.gap_mw ?? 0) > 0)
  const levers = new Map<string, { n: number; gain: number }>()
  for (const x of risk) if (x.level !== 'ok') { const f = x.focus[0]; if (f) { const v = levers.get(f.lever) ?? { n: 0, gain: 0 }; v.n += 1; v.gain += f.gain_mw ?? 0; levers.set(f.lever, v) } }
  const LEVER: Record<string, string> = { option: 'Power option (IQ)', cpu: 'CPU (EMS · 분산)', ip: 'IP clock · mode', bw: 'BW (compression · LLC)', clock: 'Timing (SW · buffering)', measure: '실측 검증' }
  const go = (page: string | undefined, r: RiskRow['row']) => page && ctx.navigate(page as Parameters<AppCtx['navigate']>[0], page === 'timing' ? conditionParams(r) : { scenario: r.scenario_id, variant: r.variant_id })
  return (
    <Card id="pr-risk" title="① Risk · Focus — 고객 성능/발열 목표 대비" defaultWide minHeight={200}
      note={`성능 = fps 유지 (timing 판정 · ${refs?.policy.throughput_model === 'pipelined' ? 'pipeline buffering 기준' : 'stage 기준'}) · SW 여유 / 소비전류 = ${pr ? `전과제 대비 (≤ +${pr.tolerance_pct}% 유사)` : target ? `목표 ${target.toFixed(0)} mW (${maText(target, battery)})` : '목표 미설정 → 상대 비교'} / 신뢰도 = 실측 · sim 검증 · range · 발열은 열 모델·동등 실측 없이 PASS 판정하지 않음 (power = 대리 지표)`}>
      {pr?.source_note && <div className="faint" style={{ fontSize: 11.5, marginBottom: 4 }}>전과제 값: {pr.project_ref ?? '직접 지정'} · {pr.source_note}</div>}
      {coverage.targets !== null && <div className="faint" style={{ fontSize: 12, marginBottom: 4 }}>
        평가 대상 variant {coverage.targets} = 등록 {coverage.targets - coverage.unregistered.length} + <b style={{ color: coverage.unregistered.length ? 'var(--del-text)' : undefined }}>미등록 {coverage.unregistered.length}</b>
        {coverage.freshChecked && <> · 등록 중 입력 변경(stale) <b style={{ color: coverage.stale ? 'var(--del-text)' : undefined }}>{coverage.stale}</b></>}
        {coverage.unregistered.length > 0 && <details style={{ display: 'inline-block', marginLeft: 8 }}><summary>미등록 목록</summary>
          <div className="mono" style={{ fontSize: 11 }}>{coverage.unregistered.map(([s, v]) => `${s} / ${v}`).join(' · ')}</div>
          <div>조합 탐색에서 실행 · 등록하면 위험 판정에 포함됩니다 (미등록 = 미평가, 통과 아님).</div></details>}
      </div>}
      {staleRows > 0 && <div className="lib-note warn" style={{ marginBottom: 6 }}>{staleRows}건은 이전 판정 기준(stage)으로 등록된 예측입니다 — 과제 기준은 pipeline buffering. 조합 탐색을 다시 실행해 등록하세요.</div>}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 8, fontSize: 12.5 }}>
        {LEVELS.map((l) => <span key={l} className={`badge ${RISK_CLASS[l]}`}>{RISK_LABEL[l]} {count(l)}</span>)}
        {(target || pr) && <span className="faint">{pr ? '전과제 초과' : '목표 초과'} {over.length}건{over.length ? ` · 최대 +${Math.max(...over.map((x) => x.gap_mw ?? 0)).toFixed(0)} mW` : ''}</span>}
        {!measuredKnown && <span className="faint">실측 coverage를 불러오지 못해 신뢰도는 sim 검증·range만 사용</span>}
        <span className="grow" />
        {[...levers].sort((a, b) => b[1].n - a[1].n).map(([k, v]) => <span key={k} className="chip" title="위험 행의 첫 번째 focus 기준">{LEVER[k] ?? k} {v.n}{v.gain ? ` · ${v.gain.toFixed(0)} mW` : ''}</span>)}
      </div>
      <div className="table-x"><table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th>Risk</th><th>Variant</th><th style={{ textAlign: 'right' }}>Power</th><th style={{ textAlign: 'right' }}>{pr ? '전과제 대비' : '목표 대비'}</th><th style={{ textAlign: 'right' }}>BW</th><th>최대 비중</th><th>위험 요인</th><th>먼저 볼 것 (focus)</th></tr></thead>
        <tbody>{shown.map((x) => (
          <tr key={x.row.id} onClick={() => onPick(x.row.id)} style={{ cursor: 'pointer' }}>
            <td><span className={`badge ${RISK_CLASS[x.level]}`}>{RISK_LABEL[x.level]}</span></td>
            <td className="mono" style={{ fontSize: 12 }}>{short(x.row.variant_id)}<div className="faint" style={{ fontSize: 10.5 }}>{x.row.scenario_id} · {fmt(x.row.fps, 0)} fps</div></td>
            <td className="mono" style={{ textAlign: 'right' }}>{fmt(x.row.power.total_mw, 0)} mW<div className="faint" style={{ fontSize: 10.5 }}>{maText(x.row.power.total_mw, battery)}</div></td>
            <td className="mono" style={{ textAlign: 'right', color: (x.gap_mw ?? -1) > 0 ? 'var(--del-text)' : undefined }}>{x.gap_mw === null ? '—' : `${x.gap_mw > 0 ? '+' : ''}${x.gap_mw.toFixed(0)}`}
              {x.judge && <div><span className={`badge ${JUDGE_CLASS[x.judge.status]}`} style={{ fontSize: 10.5 }}>{JUDGE_LABEL[x.judge.status]}</span></div>}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{fmt(x.row.bw_mbs / 1000, 2)} GB/s</td>
            <td style={{ fontSize: 12 }}>{x.dominant.part} {(100 * x.dominant.share).toFixed(0)}%</td>
            <td style={{ minWidth: 340 }}><ul className="risk-list">{x.risks.length ? x.risks.map((k) => <li key={k.text}><span className="rk">{KIND_LABEL[k.kind]}</span><span>{k.text}</span></li>) : <li className="faint">—</li>}</ul></td>
            <td style={{ minWidth: 300 }}><ul className="risk-list">{x.focus.slice(0, 3).map((f) => <li key={f.text}>
              {f.page ? <a href="#" onClick={(e) => { e.preventDefault(); e.stopPropagation(); go(f.page, x.row) }}>{f.text}</a> : f.text}
              {f.gain_mw ? <span className="mono" style={{ color: 'var(--primary-strong)' }}> {f.gain_mw.toFixed(0)} mW</span> : null}</li>)}</ul></td>
          </tr>))}</tbody>
      </table></div>
      {listed.length > 10 && <button className="btn tb-mini" style={{ marginTop: 6 }} onClick={() => setShowAll((v) => !v)}>{showAll ? '상위 10건만' : `전체 ${listed.length}건 보기`}</button>}
      <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>목표 = 고객사 성능/발열 scenario를 만족하는 power 상한. 위험 행만 표시 (양호는 상위 3건). 목표를 만족하면서 power를 더 줄일 수 있는 조건은 조합 탐색의 “화질·성능 유지” 범위에서 확인.</div>
    </Card>
  )
}
