import { useState } from 'react'
import { CPU_SOURCE_LABEL, cpuDiff, cpuDiffHeadline, cpuPickReason, EFFECT_LABEL, type CpuEffect, type CpuPick, type CpuSide } from '../lib/cpuDiff'

const EFFECT_COLOR: Record<CpuEffect, string> = { load: '#2563EB', period: '#7C3AED', coef: '#D97706', unsplit: '#64748B', added: '#16A34A', removed: '#DC2626', other: '#94A3B8' }
const sgn = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${v.toFixed(d)}`

/**
 * CPU predicted power vs ★: per item, how much each cause contributes and which tasks moved.
 * ``picks`` come from ``pickCpuSide`` (same-session run first, else stored evidence); ``onRun`` previews
 * the given items so their task rows are available for the cause split.
 */
export function CpuDiffView({ ids, labels, color, picks, onRun }: {
  ids: string[]; labels: Record<string, string>; color: (i: number) => string; picks: CpuPick[]; onRun?: (items: number[]) => void
}) {
  if (ids.length < 2) return <div className="empty">비교 항목이 2개 이상일 때 표시됩니다.</div>
  const base = picks[0]
  // items without same-session task rows (not run, stored totals only, or failed) — running them enables the split
  const needRun = ids.map((_, i) => i).filter((i) => picks[i]?.source !== 'sim' && picks[i]?.state !== 'running' && picks[i]?.state !== 'nocpu')
  const sources = new Set(picks.filter((p) => p.side).map((p) => p.source))
  const runBtn = onRun && needRun.length > 0 && <button className="btn primary tb-mini" onClick={() => onRun(needRun)}
    title="같은 기본 조건(현재 예측 기준)으로 즉석 실행 — task별 실행 시간·사용률로 원인을 분해합니다. 저장되지 않습니다.">CPU 예측 실행 ({needRun.length}개)</button>
  return <div className="cpu-diff">
    {(runBtn || sources.size > 1) && <div className="cpu-diff-bar">
      {runBtn}
      {sources.size > 1 && <span className="badge v-warn" title="저장 evidence와 즉석 실행은 모델 버전·설정이 다를 수 있습니다">출처 혼합 (저장 evidence · 즉석 실행)</span>}
    </div>}
    {!base?.side ? <div className={base?.state === 'error' ? 'err' : 'empty'}>★ {labels[ids[0]] ?? ids[0]}: {base ? cpuPickReason(base) : cpuPickReason({ side: null, source: null, state: 'none' })}</div>
      : ids.slice(1).map((id, n) => {
        const i = n + 1, p = picks[i]
        if (!p?.side) return <div key={id} className="cpu-diff-item"><b style={{ borderLeft: `4px solid ${color(i)}`, paddingLeft: 6 }}>{labels[id] ?? id}</b>{' '}
          <span className={p?.state === 'error' ? 'err-text' : 'faint'}>{p ? cpuPickReason(p) : ''}</span></div>
        return <CpuDiffItem key={id} label={labels[id] ?? id} color={color(i)} base={base.side!} side={p.side}
          source={sources.size > 1 ? `${CPU_SOURCE_LABEL[p.source!]} vs ★ ${CPU_SOURCE_LABEL[base.source!]}` : null} />
      })}
    <details className="faint" style={{ fontSize: 12 }}><summary>계산 방법</summary>
      task 전력 P = k · a / T (a = frame당 CPU active ms, T = frame 주기, k = 해당 cluster·OPP의 100% 사용 시 mW).
      ★ 대비 변화를 순서대로 나눕니다: SW 부하 = k★·Δa/T★ · 주기 = k★·a·Δ(1/T) · 배치·계수 = Δk·a/T. 세 항의 합 = task Δ (정확히 일치).
      task 추가/제거 = variant별 SW task 정의(sw_timing의 absent_in 등) 차이입니다 — 실제 부하 변화가 아니라 모델 범위 차이일 수 있습니다.
      출처: 이 화면에서 실행한 결과(즉석)가 있으면 그것을, 없으면 저장된 simulation evidence의 합계를 씁니다. task 행이 없는 결과는 task별 Δ만 보여줍니다.</details>
  </div>
}

function CpuDiffItem({ label, color, base, side, source }: { label: string; color: string; base: CpuSide; side: CpuSide; source: string | null }) {
  const [all, setAll] = useState(false)
  const d = cpuDiff(base, side)
  const effects = (Object.entries(d.effects) as [CpuEffect, number][]).filter(([, v]) => Math.abs(v) >= 0.05)
  const scale = Math.max(1e-9, ...effects.map(([, v]) => Math.abs(v)))
  const tasks = d.tasks.filter((t) => Math.abs(t.delta) >= 0.01)
  const shown = all ? tasks : tasks.slice(0, 8)
  return <div className="cpu-diff-item">
    <div className="cpu-diff-head"><b style={{ borderLeft: `4px solid ${color}`, paddingLeft: 6 }}>{label}</b>
      <span className="mono">CPU {d.base.toFixed(1)} → {d.cand.toFixed(1)} mW</span>
      <span className={`mono ${d.delta > 0 ? 'cpu-up' : d.delta < 0 ? 'cpu-down' : ''}`}>{cpuDiffHeadline(d)}</span>
      {source && <span className="faint">{source}</span>}
      {!d.detailed && <span className="badge v-warn" title="task별 실행 시간·사용률이 있는 결과(즉석 예측 실행)에서만 원인을 분해합니다 — “CPU 예측 실행”">원인 분해 불가 · 합계만</span>}</div>
    {effects.length > 0 && <div className="cpu-effects">{effects.map(([k, v]) => <div key={k} className="cpu-effect-row">
      <span className="cpu-effect-label">{EFFECT_LABEL[k]}</span>
      <span className="cpu-effect-track"><span className="cpu-effect-mid" />
        <span className="cpu-effect-bar" style={{ background: EFFECT_COLOR[k], width: `${(Math.abs(v) / scale) * 50}%`, left: v >= 0 ? '50%' : `${50 - (Math.abs(v) / scale) * 50}%` }} /></span>
      <span className="mono cpu-effect-val">{sgn(v)} mW</span></div>)}</div>}
    {d.clusters.some((c) => Math.abs(c.delta) >= 0.05) && <p className="faint" style={{ margin: '4px 0' }}>cluster: {d.clusters.filter((c) => Math.abs(c.delta) >= 0.05).map((c) => `${c.name} ${c.base.toFixed(1)}→${c.cand.toFixed(1)} (${sgn(c.delta)})`).join(' · ')}</p>}
    {tasks.length > 0 && <div className="table-x"><table className="tb-mini-table" style={{ width: '100%' }}>
      <thead><tr><th>task</th><th>cluster</th><th style={{ textAlign: 'right' }}>★ mW</th><th style={{ textAlign: 'right' }}>mW</th><th style={{ textAlign: 'right' }}>Δ</th>
        {d.detailed && <><th style={{ textAlign: 'right' }}>SW 부하</th><th style={{ textAlign: 'right' }}>주기</th><th style={{ textAlign: 'right' }}>배치·계수</th></>}<th>근거</th></tr></thead>
      <tbody>{shown.map((t) => <tr key={t.task}>
        <th className="mono">{t.task}{t.kind !== 'both' && <span className={`badge ${t.kind === 'added' ? 'v-ok' : 'v-warn'}`} style={{ marginLeft: 4 }}>{t.kind === 'added' ? '추가' : '제거'}</span>}</th>
        <td className="mono">{t.clusterBase && t.clusterCand && t.clusterBase !== t.clusterCand ? `${t.clusterBase}→${t.clusterCand}` : t.clusterCand ?? t.clusterBase ?? ''}</td>
        <td className="mono" style={{ textAlign: 'right' }}>{t.base.toFixed(2)}</td><td className="mono" style={{ textAlign: 'right' }}>{t.cand.toFixed(2)}</td>
        <td className="mono" style={{ textAlign: 'right' }}>{sgn(t.delta, 2)}</td>
        {d.detailed && (['load', 'period', 'coef'] as const).map((k) => <td key={k} className="mono" style={{ textAlign: 'right' }}>{t.effects[k] !== undefined ? sgn(t.effects[k]!, 2) : ''}</td>)}
        <td className="faint">{t.reasons.join(' · ')}</td></tr>)}</tbody></table></div>}
    {tasks.length > 8 && <button className="btn tb-mini" onClick={() => setAll((v) => !v)}>{all ? '상위 8개만' : `전체 ${tasks.length}개 보기`}</button>}
  </div>
}
