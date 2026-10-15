import { useState } from 'react'
import { cpuDiff, cpuDiffHeadline, EFFECT_LABEL, type CpuEffect, type CpuSide } from '../lib/cpuDiff'

const EFFECT_COLOR: Record<CpuEffect, string> = { load: '#2563EB', period: '#7C3AED', coef: '#D97706', unsplit: '#64748B', added: '#16A34A', removed: '#DC2626', other: '#94A3B8' }
const sgn = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${v.toFixed(d)}`

/** CPU predicted power vs ★: per item, how much each cause contributes and which tasks moved. */
export function CpuDiffView({ ids, labels, color, sides }: { ids: string[]; labels: Record<string, string>; color: (i: number) => string; sides: (CpuSide | null)[] }) {
  const base = sides[0]
  if (ids.length < 2) return <div className="empty">비교 항목이 2개 이상일 때 표시됩니다.</div>
  if (!base) return <div className="empty">★ 기준에 CPU 예측 전력이 없습니다 — “예측 실행”(power params에 cpu 블록)으로 계산하면 원인을 분해합니다.</div>
  return <div className="cpu-diff">
    {ids.slice(1).map((id, n) => {
      const i = n + 1, side = sides[i]
      if (!side) return <div key={id} className="cpu-diff-item"><b style={{ borderLeft: `4px solid ${color(i)}`, paddingLeft: 6 }}>{labels[id] ?? id}</b> <span className="faint">CPU 예측 전력 없음</span></div>
      return <CpuDiffItem key={id} label={labels[id] ?? id} color={color(i)} base={base} side={side} />
    })}
    <details className="faint" style={{ fontSize: 12 }}><summary>계산 방법</summary>
      task 전력 P = k · a / T (a = frame당 CPU active ms, T = frame 주기, k = 해당 cluster·OPP의 100% 사용 시 mW).
      ★ 대비 변화를 순서대로 나눕니다: SW 부하 = k★·Δa/T★ · 주기 = k★·a·Δ(1/T) · 배치·계수 = Δk·a/T. 세 항의 합 = task Δ (정확히 일치).
      task 행이 없는 결과(저장 evidence의 합계만)는 task별 Δ만 보여줍니다.</details>
  </div>
}

function CpuDiffItem({ label, color, base, side }: { label: string; color: string; base: CpuSide; side: CpuSide }) {
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
      {!d.detailed && <span className="badge v-warn" title="task별 실행 시간·사용률이 있는 결과(즉석 예측 실행)에서만 원인을 분해합니다">원인 분해 불가 · 합계만</span>}</div>
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
