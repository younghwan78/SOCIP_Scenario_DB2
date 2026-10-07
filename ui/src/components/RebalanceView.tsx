// CPU what-if "MID 재분배": setup (pool, task states, co-move) and results (move curve, top splits, OPP states, boundaries).
import { useMemo, useState } from 'react'
import { fmt } from '../lib/timingBudget'
import { partColor, sortClusters } from '../lib/powerModel'
import { applyDsuRebalance, bigVerdict, strategyVerdict, type CpuRebalance, type RbBoundary, type RbSplit, type RbStrategyRow } from '../lib/rebalance'
import { shiftVote, type DsuPolicy } from '../lib/dsu'
import { useTip } from './ChartTip'
import { useWidth } from './Charts'
import { DataTable, type Column } from './DataTable'
import { Card } from './TimingCharts'
import { CPU_HELP } from './CpuHelp'

export type TaskState = 'auto' | 'exclude' | `pin:${string}`
export type Knob = 'cpuset' | 'affinity'
export const KNOB_LABEL: Record<Knob, string> = { cpuset: 'cpuset', affinity: 'affinity' }
export const KNOB_NOTE: Record<Knob, string> = {
  cpuset: 'process / cgroup 단위 (init.rc · task_profiles) — 가장 쉽게 적용, task가 thread를 여럿 가지면 함께 이동',
  affinity: 'thread 단위 sched_setaffinity (HAL 코드 수정) — 세밀하지만 SW 변경 필요',
}
/** Android cpuset cgroups (task_profiles / EMS tuning pin per cgroup). Group = cgroup: members move to the same cluster. */
export const CGROUPS: { id: string; short: string; note: string }[] = [
  { id: 'camera-daemon', short: 'cam', note: 'camera-daemon — cameraserver · camera provider(HAL) · 3A/algo daemon' },
  { id: 'top-app', short: 'top', note: 'top-app — 화면 앞 app (camera app UI · RenderThread)' },
  { id: 'foreground', short: 'fg', note: 'foreground — media codec · audio 등 foreground service' },
  { id: 'system-background', short: 'sys', note: 'system-background — system daemon' },
  { id: 'background', short: 'bg', note: 'background' },
]
const GROUP_OPTS = [{ value: '', label: '—', title: 'cgroup 미지정 — task 단독으로 이동' },
  ...CGROUPS.map((g) => ({ value: g.id, label: g.short, title: `${g.note} · 같은 cgroup = 같은 cluster로 함께 pinning` }))]
const OTHER = '#C9C2B6'
const signed = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${fmt(v, d)}`

/** "MID_LF0" → "LF0" for compact segment labels (full name stays in the title). */
export const shortCluster = (c: string) => c.replace(/^MID_/, '')

/** In-page segmented control (radiogroup). Replaces native <select> in dense tables: no OS popup, one click per change. */
export function Seg({ label, value, options, onChange, disabled }: {
  label: string; value: string; disabled?: boolean; onChange: (v: string) => void
  options: { value: string; label: string; title?: string; color?: string }[]
}) {
  return <div className={`seg xs${disabled ? ' off' : ''}`} role="radiogroup" aria-label={label} aria-disabled={disabled || undefined}>
    {options.map((o) => {
      const on = o.value === value
      return <button key={o.value} type="button" role="radio" aria-checked={on} data-value={o.value} className={on ? 'on' : ''}
        title={o.title} disabled={disabled} onClick={() => { if (!on) onChange(o.value) }}
        style={on && o.color ? { boxShadow: `inset 0 -2px 0 ${o.color}, 0 1px 2px rgba(31,36,48,.12)` } : undefined}>{o.label}</button>
    })}
  </div>
}

export interface SetupRow { task: string; home: string; budget: number | null; util?: Record<string, number>; tms?: Record<string, number> }

/** ③ 분배 대상 — pool clusters, per-task state, co-move groups. Edits never start a run by themselves. */
export function RebalanceSetup({ clusters, pool, setPool, rows, states, setState, groups, setGroup, budgets, setBudget, space, method, busy, onRun, top, setTop, hasResult, knob, setKnob }: {
  clusters: string[]; pool: string[]; setPool: (p: string[]) => void
  rows: SetupRow[]; states: Record<string, TaskState>; setState: (task: string, s: TaskState) => void
  groups: Record<string, string>; setGroup: (task: string, g: string) => void
  budgets: Record<string, string>; setBudget: (task: string, v: string) => void
  space: { units: number; splits: number; reduced: number }; method?: string
  busy: boolean; onRun: () => void; top: number; setTop: (n: number) => void; hasResult: boolean
  knob: Knob; setKnob: (k: Knob) => void
}) {
  const keys = clusters.map((c) => `cpu.${c}`)
  const color = (c: string) => partColor(`cpu.${c}`, keys)
  const inPool = (c: string) => pool.includes(c)
  return (
    <Card id="cpu-rb-setup" title="③ 분배 대상" defaultWide help={CPU_HELP.rbSetup}
      note="pool cluster 사이에서 task를 cpuset으로 나눔 · 자동 = 계산이 고름 · 고정 / 제외 = 그대로 둠 · 같은 측정 cluster의 task만 같은 cgroup으로 함께 pinning">
      <div className="toolbar" style={{ gap: 10, fontSize: 12, marginBottom: 6, flexWrap: 'wrap' }}>
        <span className="faint">pool</span>
        {clusters.map((c) => <label key={c} style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
          <input type="checkbox" checked={inPool(c)} onChange={() => setPool(inPool(c) ? pool.filter((x) => x !== c) : sortClusters([...pool, c]))} />
          <span className="sw pm-sw" style={{ background: color(c) }} />{c}</label>)}
        {pool.length < 2 && <span className="badge v-fail">cluster 2개 이상 필요</span>}
        <span className="faint">· BIG 계열은 기본 제외 (camera SW는 대체로 손해)</span>
        <span className="grow" />
        <label className="faint" style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }} title={KNOB_NOTE[knob]}>적용 방법
          <select value={knob} aria-label="적용 방법" onChange={(e) => setKnob(e.target.value as Knob)}>
            <option value="cpuset">cpuset (process 단위)</option><option value="affinity">affinity (thread 단위)</option></select></label>
      </div>
      <CgroupSummary rows={rows} groups={groups} states={states} pool={pool} />
      <div className="table-x"><table className="grid cpu-matrix rb-setup">
        <thead><tr><th>task</th><th>측정 위치</th>
          {pool.map((c) => <th key={c} style={{ borderTop: `3px solid ${color(c)}`, textAlign: 'right' }} title="fmax에서 task 시간 (가장 긴 thread) · util">{c}<div className="faint" style={{ fontSize: 10.5, fontWeight: 400 }}>ms @fmax · util</div></th>)}
          <th title="frame당 허용 시간 (가장 긴 thread)">budget ms</th><th>상태</th><th title="cpuset cgroup — 같은 cgroup의 task는 같은 cluster로 함께 pinning (task_profiles · EMS tuning 방식). 가정값: 사용자가 지정, task 이름 기준으로 기억 · TBD: cgroup 구성·분리 비용 data 없음 — 지금은 같은 cluster 제약만 적용">cgroup (함께 이동) <span className="badge">TBD</span></th></tr></thead>
        <tbody>{rows.map((r) => {
          const st = states[r.task] ?? 'auto'
          const movable = inPool(r.home)
          return <tr key={r.task} className={st === 'auto' && movable ? '' : 'row-off'}>
            <td className="mono">{r.task}</td>
            <td><span className="sw pm-sw" style={{ background: color(r.home) }} />{r.home}{!movable && <span className="faint" style={{ fontSize: 11 }}> · pool 밖 (고정)</span>}</td>
            {pool.map((c) => <td key={c} className={`mono ${c === r.home ? 'measured' : ''}`} style={{ textAlign: 'right' }}>
              {r.tms?.[c] !== undefined ? <>{fmt(r.tms[c], 2)}<span className="faint"> · {fmt(r.util?.[c] ?? 0, 0)}</span></> : <span className="faint">—</span>}</td>)}
            <td><input style={{ width: 52 }} value={budgets[r.task] ?? ''} placeholder={r.budget !== null ? String(r.budget) : '—'} onChange={(e) => setBudget(r.task, e.target.value)} aria-label={`${r.task} budget`} /></td>
            <td><Seg label={`${r.task} 상태`} value={st} disabled={!movable} onChange={(v) => setState(r.task, v as TaskState)}
              options={[{ value: 'auto', label: '자동', title: '계산이 cluster를 고름' },
                ...pool.map((c) => ({ value: `pin:${c}`, label: shortCluster(c), title: `${c} 고정`, color: color(c) })),
                { value: 'exclude', label: '제외', title: '제외 — 측정 위치에 그대로 둠' }]} /></td>
            <td><Seg label={`${r.task} 함께 이동`} value={groups[r.task] ?? ''} disabled={!movable || st !== 'auto'} onChange={(v) => setGroup(r.task, v)}
              options={GROUP_OPTS} /></td>
          </tr>
        })}</tbody></table></div>
      <div className="toolbar" style={{ marginTop: 8, gap: 10 }}>
        <span className="faint" style={{ fontSize: 12 }}>이동 단위 {space.units}개 · 분할 {pool.length}^{space.units} = {space.splits.toLocaleString()}{space.reduced !== space.splits ? ` (동일 cluster 대칭 제거 ≈ ${space.reduced.toLocaleString()})` : ''}
          {' · '}{space.reduced <= 300000 ? '전수 계산' : '국소 탐색 (move / swap)'}{method ? ` · 지난 계산: ${method === 'exhaustive' ? '전수' : '국소 탐색'}` : ''}</span>
        <span className="grow" />
        <label className="faint" style={{ fontSize: 12, display: 'flex', gap: 4, alignItems: 'center' }}>결과 상위
          <select value={top} onChange={(e) => setTop(Number(e.target.value))} aria-label="재분배 결과 상위 N">{[10, 20, 50].map((n) => <option key={n} value={n}>{n}</option>)}</select>개</label>
        <button className="btn primary" disabled={busy || pool.length < 2} onClick={onRun}>{busy ? '계산 중…' : hasResult ? '다시 계산' : '재분배 계산'}</button>
      </div>
    </Card>
  )
}

/** cgroup membership at a glance: which tasks move as one unit (only cgroups with members). */
function CgroupSummary({ rows, groups, states, pool }: { rows: SetupRow[]; groups: Record<string, string>; states: Record<string, TaskState>; pool: string[] }) {
  const used = CGROUPS.map((g) => ({ g, tasks: rows.filter((r) => groups[r.task] === g.id) })).filter((x) => x.tasks.length)
  if (!used.length) return <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}><span className="badge">TBD</span> cgroup 미지정 — task마다 따로 이동 · 오른쪽 열에서 cgroup을 지정하면 같은 cgroup끼리 같은 cluster로 묶음 (가정값, task 이름 기준으로 기억)</div>
  return <div className="toolbar cg-summary" aria-label="cgroup 구성" style={{ gap: 8, fontSize: 12, marginBottom: 6, flexWrap: 'wrap' }}>
    <span className="faint">cgroup</span><span className="badge" title="cgroup 구성·분리 비용 data 없음 — 같은 cluster 제약만 적용">TBD</span>
    {used.map(({ g, tasks }) => {
      const active = tasks.filter((r) => pool.includes(r.home) && (states[r.task] ?? 'auto') === 'auto')
      return <span key={g.id} className="chip" title={`${g.note}\n${tasks.map((r) => r.task).join(', ')}`}>
        <b>{g.id}</b> {active.length}{active.length !== tasks.length ? `/${tasks.length}` : ''} task{active.length > 1 ? ' → 1 단위' : ''}</span>
    })}
  </div>
}

/** Stack / legend order for power breakdowns: DSU first, then pool clusters in topology order, then the clusters outside the pool
 * (aggregated as `other` by the server — named after them, e.g. BIG). Bottom→top in the curve, left→right in the bars. */
export function powerParts(r: CpuRebalance): { k: string; label: string; color: string }[] {
  const keys = r.clusters.map((c) => `cpu.${c.name}`)
  const outside = sortClusters(r.clusters.map((c) => c.name).filter((c) => !r.pool.includes(c)))
  return [{ k: 'dsu', label: 'DSU', color: partColor('cpu.dsu', keys) },
    ...sortClusters([...r.pool]).map((c) => ({ k: c, label: c, color: partColor(`cpu.${c}`, keys) })),
    { k: 'other', label: outside.length ? `${outside.join(' + ')} (pool 밖)` : 'pool 밖', color: outside.length === 1 ? partColor(`cpu.${outside[0]}`, keys) : OTHER }]
}

/** Greedy move curve: stacked power per step (pool clusters · DSU · other), total line, ★ start, ● lowest. */
export function MoveCurve({ r, sel, onPick }: { r: CpuRebalance; sel: string; onPick: (id: string) => void }) {
  const [ref, width] = useWidth<HTMLDivElement>(800)
  const tip = useTip()
  const parts = powerParts(r)
  const pts = r.curve
  const max = Math.max(...pts.map((p) => p.total_mw), r.reference.total_mw) * 1.08
  const H = 220, L = 46, B = 92, plotW = Math.max(200, width - L - 12), bw = Math.min(46, (plotW / pts.length) * 0.7)
  const x = (i: number) => L + (i + 0.5) * (plotW / pts.length)
  const y = (v: number) => 8 + (1 - v / max) * (H - 8)
  const lowest = pts.reduce((b, p, i) => (p.feasible && (b < 0 || p.total_mw < pts[b].total_mw) ? i : b), -1)
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max)
  return (
    <div ref={ref} style={{ width: '100%' }}>
      <div className="legend-row">{parts.map((p) => <span key={p.k} className="legend-item"><span className="sw" style={{ background: p.color }} />{p.label}</span>)}
        <span className="legend-item faint">— 총 CPU mW · ★ 현재 · ● 곡선 최저 · 점선 = 전체 탐색 최저 · 흐린 막대 = budget 미충족</span></div>
      <svg width={width} height={H + B} role="img" aria-label="이동 곡선">
        {ticks.map((t) => <g key={t}><line x1={L} x2={L + plotW} y1={y(t)} y2={y(t)} stroke="#EFEAE2" /><text x={L - 6} y={y(t) + 4} fontSize={10} textAnchor="end" fill="var(--muted)">{fmt(t, 0)}</text></g>)}
        {r.best && <line x1={L} x2={L + plotW} y1={y(r.best.total_mw)} y2={y(r.best.total_mw)} stroke="#2F855A" strokeDasharray="5 4"><title>전체 탐색 최저 {fmt(r.best.total_mw, 1)} mW</title></line>}
        {pts.map((p, i) => {
          let acc = 0
          const id = `s${i}`
          return <g key={i} opacity={p.feasible ? 1 : 0.35} style={{ cursor: 'pointer' }} onClick={() => onPick(id)}
            {...tip(() => ({ title: i === 0 ? '현재 (측정 배치)' : `step ${i} · ${p.moved_unit} 이동`, head: { label: '총 CPU', value: `${fmt(p.total_mw, 1)} mW`, tone: 'strong' as const },
              rows: [{ k: '현재 대비', v: `${signed(p.delta_mw)} mW`, tone: p.delta_mw < 0 ? 'good' as const : 'bad' as const },
                ...parts.map((q) => ({ k: q.label, v: `${fmt(p.mw[q.k] ?? 0, 1)} mW${p.mhz[q.k] ? ` @${p.mhz[q.k]}` : ''}`, color: q.color })),
                { k: '옮긴 util', v: `${p.moved_util_pct ?? 0}%` }, { k: '판정', v: p.feasible ? 'budget 충족' : '미충족', tone: p.feasible ? 'good' as const : 'bad' as const }] }))}>
            {parts.map((q) => { const v = p.mw[q.k] ?? 0; const y0 = y(acc + v), h = y(acc) - y0; acc += v
              return <rect key={q.k} x={x(i) - bw / 2} y={y0} width={bw} height={Math.max(0, h)} fill={q.color} stroke={sel === id ? '#1F2430' : 'none'} /> })}
            <text x={x(i)} y={H + 14} fontSize={10} textAnchor="middle" fill="var(--muted)">{i}</text>
            <text x={x(i) + 3} y={H + 26} fontSize={9.5} textAnchor="end" fill="var(--text-2)" transform={`rotate(-35 ${x(i) + 3} ${H + 26})`}>{i === 0 ? '현재' : p.moved_unit}</text>
          </g>
        })}
        <polyline points={pts.map((p, i) => `${x(i)},${y(p.total_mw)}`).join(' ')} fill="none" stroke="#1F2430" strokeWidth={1.5} />
        {pts.map((p, i) => <circle key={i} cx={x(i)} cy={y(p.total_mw)} r={2.5} fill="#1F2430" />)}
        <text x={x(0)} y={y(pts[0].total_mw) - 8} fontSize={13} textAnchor="middle">★</text>
        {lowest > 0 && <circle cx={x(lowest)} cy={y(pts[lowest].total_mw)} r={6} fill="none" stroke="#2F855A" strokeWidth={2} />}
      </svg>
    </div>
  )
}

function SplitDetail({ s, r, title, knob = 'cpuset' }: { s: RbSplit; r: CpuRebalance; title: string; knob?: Knob }) {
  const units = r.units
  return (
    <Card id="cpu-rb-detail" title={title} defaultWide note="task별 cluster · 시간 · budget" help={CPU_HELP.rbDetail}>
      <div className="toolbar" style={{ gap: 12, fontSize: 12, flexWrap: 'wrap', marginBottom: 6 }}>
        {r.pool.map((c) => <span key={c} className="mono">{c} <b>{s.mhz[c]}</b> MHz ({fmt(s.mw[c] ?? 0, 1)} mW · {r.reference.mhz[c]}→{s.mhz[c]})</span>)}
        <span className="mono">DSU <b>{s.mhz.dsu}</b> MHz ({fmt(s.mw.dsu ?? 0, 1)} mW)</span>
        {s.knobs.length > 0 && <span className="badge" title={KNOB_NOTE[knob]}>{KNOB_LABEL[knob]} {s.knobs.length}건</span>}
      </div>
      <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th>task</th><th>측정 → 배치</th><th style={{ textAlign: 'right' }}>task ms</th><th style={{ textAlign: 'right' }}>budget</th><th style={{ textAlign: 'right' }}>slack</th></tr></thead>
        <tbody>{units.flatMap((u) => u.tasks.map((t) => {
          const at = s.assign[u.unit] ?? u.home, ms = s.task_ms?.[t], sl = s.slack_ms?.[t]
          return <tr key={t}><td className="mono">{t}{u.tasks.length > 1 && <span className="faint"> ({u.unit})</span>}</td>
            <td>{u.home}{at !== u.home ? <b> → {at}</b> : ''}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{ms !== undefined ? fmt(ms, 2) : '—'}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{u.budget_ms ?? '—'}</td>
            <td className={`mono ${sl !== undefined && sl < 0 ? 'pm-up' : ''}`} style={{ textAlign: 'right' }}>{sl !== undefined ? fmt(sl, 2) : '—'}</td></tr>
        }))}</tbody>
      </table>
    </Card>
  )
}

function Boundaries({ list, title }: { list: RbBoundary[]; title: string }) {
  return <div>
    <h3 className="cpu-h">{title}</h3>
    <table className="tb-mini-table" style={{ width: '100%' }}>
      <thead><tr><th>cluster</th><th style={{ textAlign: 'right' }}>MHz (mV)</th><th style={{ textAlign: 'right' }}>1 step ↓</th><th style={{ textAlign: 'right' }}>빼야 할 util</th><th>후보 (util)</th></tr></thead>
      <tbody>{list.map((b) => <tr key={b.cluster}><td className="mono">{b.cluster}</td>
        <td className="mono" style={{ textAlign: 'right' }}>{b.mhz} ({b.mv})</td>
        <td className="mono" style={{ textAlign: 'right' }}>{b.next_lower_mhz ? `${b.next_lower_mhz} (${b.next_lower_mv})` : '최저 OPP'}</td>
        <td className="mono" style={{ textAlign: 'right' }} title={b.boosted_by?.length ? `schedutil은 ${b.sched_mhz} MHz지만 budget 때문에 올림: ${b.boosted_by.join(', ')}` : undefined}>
          {b.boosted_by?.length ? <span className="badge v-warn">budget ↑ {b.boosted_by.slice(0, 2).join(', ')}{b.boosted_by.length > 2 ? '…' : ''}</span> : (b.delta_util_needed ?? '—')}</td>
        <td className="mono faint" style={{ fontSize: 11 }}>{(b.candidates ?? []).filter(([, u]) => u >= (b.delta_util_needed ?? 0)).slice(0, 5).map(([t, u]) => `${t} (${fmt(u, 0)})`).join(' · ') || '—'}</td></tr>)}</tbody>
    </table>
  </div>
}

export function RebalanceResults({ r, sel, setSel, knob = 'cpuset', sensitivity, onPickStrategy }: { r: CpuRebalance; sel: string; setSel: (id: string) => void; knob?: Knob; sensitivity?: React.ReactNode
  /** pin every task of a strategy row (setup ③ 고정) */
  onPickStrategy?: (assign: Record<string, string>) => void }) {
  const ref = r.reference, best = r.best
  const parts = powerParts(r)
  const picked: RbSplit | undefined = sel === 'ref' ? ref : sel.startsWith('c') ? r.cases.find((c) => `c${c.rank}` === sel) : sel.startsWith('s') ? r.curve[Number(sel.slice(1))] : undefined
  const maxMw = Math.max(ref.total_mw, ...r.cases.map((c) => c.total_mw))
  const cols: Column<RbSplit>[] = useMemo(() => [
    { key: 'rank', label: '#', width: 40, sort: (c) => c.rank, render: (c) => c.rank },
    { key: 'mw', label: 'CPU mW', width: 84, align: 'right', sort: (c) => c.total_mw, render: (c) => <span className="mono">{fmt(c.total_mw, 1)}</span> },
    { key: 'd', label: '현재 대비', width: 90, align: 'right', sort: (c) => c.delta_mw, render: (c) => <span className={`mono ${c.delta_mw < 0 ? 'pm-down' : 'pm-up'}`}>{signed(c.delta_mw)}</span> },
    { key: 'stack', label: '구성', width: 170, render: (c) => <span className="rb-stack" title={parts.map((q) => `${q.label} ${fmt(c.mw[q.k] ?? 0, 1)}`).join(' · ')}>
      {parts.map((q) => <span key={q.k} style={{ width: `${(100 * (c.mw[q.k] ?? 0)) / maxMw}%`, background: q.color }} />)}</span> },
    ...r.pool.map((cl): Column<RbSplit> => ({ key: `f.${cl}`, label: cl, width: 86, align: 'right', sort: (c) => c.mhz[cl], render: (c) => <span className={`mono ${c.mhz[cl] < ref.mhz[cl] ? 'pm-down' : c.mhz[cl] > ref.mhz[cl] ? 'pm-up' : ''}`}>{c.mhz[cl]}</span> })),
    { key: 'dsu', label: 'DSU', width: 64, align: 'right', sort: (c) => c.mhz.dsu, render: (c) => <span className="mono">{c.mhz.dsu}</span> },
    { key: 'slack', label: 'slack ms', width: 76, align: 'right', sort: (c) => c.min_slack_ms ?? null, render: (c) => <span className="mono">{c.min_slack_ms === null || c.min_slack_ms === undefined ? '—' : fmt(c.min_slack_ms, 2)}</span> },
    { key: 'mv', label: '옮긴 task → cluster', width: 420, title: (c) => c.moved.map((u) => `${u}→${c.assign[u]}`).join('\n'), render: (c) => <span className="mono faint" style={{ fontSize: 11.5 }}>{c.moved.map((u) => `${u}→${c.assign[u]}`).join(' · ') || <span className="badge">현재 배치 그대로</span>}</span> },
  ], [r]) // eslint-disable-line react-hooks/exhaustive-deps
  const tile = (label: string, value: string, note: string, tone = '') =>
    <div key={label} className="panel tb-kpi"><div className="faint" style={{ fontSize: 12 }}>{label}</div><div className={`mono ${tone}`} style={{ fontSize: 20, fontWeight: 600 }}>{value}</div><div className="faint" style={{ fontSize: 11 }}>{note}</div></div>
  return <>
    <div className="tb-kpis">
      {tile('현재 (측정 배치)', `${fmt(ref.total_mw, 1)} mW`, r.pool.map((c) => `${c} ${ref.mhz[c]}`).join(' · ') + ` · DSU ${ref.mhz.dsu}`)}
      {best && tile('최저 분배', `${fmt(best.total_mw, 1)} mW`, r.pool.map((c) => `${c} ${best.mhz[c]}`).join(' · ') + ` · DSU ${best.mhz.dsu}`, 'pm-down')}
      {best && tile('절감', `${signed(best.delta_mw)} mW`, `${fmt((100 * best.delta_mw) / ref.total_mw, 1)}% · task ${best.moved.length}개 이동`, best.delta_mw < 0 ? 'pm-down' : '')}
      {tile('탐색', r.method === 'exhaustive' ? '전수' : '국소 탐색', `분할 ${r.evaluated.toLocaleString()} / ${r.space.toLocaleString()} · 조건 충족 ${r.feasible_count.toLocaleString()} · 정밀 검증 ${r.verified}`)}
    </div>
    {r.warnings.filter((w) => !/max_exhaustive/.test(w)).map((w) => <div key={w} className="lib-note warn">{/no same-name/.test(w) ? `측정 cluster 대응 없음 — ${w}` : w}</div>)}
    <StrategyCard r={r} onPickCase={onPickStrategy} />
    <Card id="cpu-rb-curve" title="이동 곡선" defaultWide help={CPU_HELP.rbCurve} note="현재 배치에서 이득이 큰 task부터 하나씩 옮김 · 막대 클릭 = 아래 상세">
      <MoveCurve r={r} sel={sel} onPick={setSel} />
    </Card>
    <Card id="cpu-rb-top" title={`최저 분배 상위 ${r.cases.length}`} defaultWide help={CPU_HELP.rbTop} note="budget 충족 · CPU+DSU 전력 낮은 순 · 행 클릭 = 상세" minHeight={160}>
      <div className="table-scroll" style={{ maxHeight: 360 }}>
        <DataTable id="cpu.rb.top" columns={cols} rows={r.cases} rowKey={(c) => `c${c.rank}`} rowClass={(c) => (sel === `c${c.rank}` ? 'sel' : '')} onRowClick={(c) => setSel(`c${c.rank}`)} />
      </div>
    </Card>
    <Card id="cpu-rb-states" title="OPP 상태별 묶음" help={CPU_HELP.rbStates} note={`같은 cluster OPP 조합 = 전력 차이 작음 · ${r.opp_state_count}개 상태`} minHeight={120}>
      <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr>{r.pool.map((c) => <th key={c} style={{ textAlign: 'right' }}>{c}</th>)}<th style={{ textAlign: 'right' }}>DSU</th><th style={{ textAlign: 'right' }}>분할 수</th><th style={{ textAlign: 'right' }}>mW 범위</th></tr></thead>
        <tbody>{r.opp_states.slice(0, 12).map((s, i) => <tr key={i}>{r.pool.map((c) => <td key={c} className="mono" style={{ textAlign: 'right' }}>{s.mhz[c]}</td>)}
          <td className="mono" style={{ textAlign: 'right' }}>{s.mhz.dsu}</td><td className="mono" style={{ textAlign: 'right' }}>{s.count.toLocaleString()}</td>
          <td className="mono" style={{ textAlign: 'right' }}>{fmt(s.min_mw, 1)}–{fmt(s.max_mw, 1)}</td></tr>)}</tbody>
      </table>
    </Card>
    <Card id="cpu-rb-bound" title="OPP 경계" help={CPU_HELP.rbBound} note="cluster를 한 단계 낮추려면 빼야 할 util과 후보 task" minHeight={120}>
      <div style={{ display: 'grid', gap: 10 }}>
        <Boundaries list={r.boundaries.reference} title="현재" />
        {best && <Boundaries list={r.boundaries.best} title="최저 분배" />}
      </div>
    </Card>
    {sensitivity}
    {picked && <SplitDetail s={picked} r={r} knob={knob} title={sel === 'ref' ? '현재 (측정 배치)' : picked.rank ? `#${picked.rank} 분배 상세` : `곡선 step ${picked.step}`} />}
  </>
}

/** C6: the same measured profile rebalanced on two projects' CPU topologies. */
export function CrossSocCompare({ a, b, aName, bName, error, busy }: { a: CpuRebalance; b: CpuRebalance | null; aName: string; bName: string; error: string | null; busy: boolean }) {
  const col = (r: CpuRebalance) => {
    const best = r.best
    return {
      pool: r.pool.join(' / '), ref: r.reference.total_mw, best: best?.total_mw ?? null, d: best ? best.delta_mw : null,
      refMhz: r.pool.map((c) => `${c} ${r.reference.mhz[c]}`).join(' · ') + ` · DSU ${r.reference.mhz.dsu}`,
      bestMhz: best ? r.pool.map((c) => `${c} ${best.mhz[c]}`).join(' · ') + ` · DSU ${best.mhz.dsu}` : '—',
      moved: best ? best.moved.length : 0, sym: r.symmetric.map((x) => x.join('=')).join(', ') || '—', method: r.method === 'exhaustive' ? '전수' : '국소 탐색',
      warn: r.warnings.filter((w) => !/max_exhaustive/.test(w)),
    }
  }
  const A = col(a), B = b ? col(b) : null
  const rows: [string, (x: ReturnType<typeof col>) => string, ((x: ReturnType<typeof col>) => string)?][] = [
    ['pool', (x) => x.pool], ['현재 배치', (x) => `${fmt(x.ref, 1)} mW`], ['현재 clock', (x) => x.refMhz],
    ['최저 분배', (x) => (x.best === null ? '—' : `${fmt(x.best, 1)} mW`), (x) => (x.d === null ? '' : `${signed(x.d)} mW`)], ['최저 clock', (x) => x.bestMhz],
    ['옮긴 task', (x) => `${x.moved}개`], ['동일 cluster', (x) => x.sym], ['탐색', (x) => x.method],
  ]
  return (
    <Card id="cpu-rb-cross" title="과제 비교" defaultWide minHeight={120} help={CPU_HELP.rbCross} note="같은 측정 profile · 같은 budget · 같은 DSU 규칙으로 두 과제 CPU 구성에서 재분배">
      {error && <div className="err">{error}</div>}
      <table className="tb-mini-table" style={{ width: '100%' }} aria-label="과제 비교">
        <thead><tr><th /><th>{aName}</th><th>{bName}</th><th style={{ textAlign: 'right' }}>차이 ({bName} − {aName})</th></tr></thead>
        <tbody>{rows.map(([k, f, sub]) => <tr key={k}><td className="faint">{k}</td>
          <td className="mono">{f(A)}{sub && <span className="faint"> {sub(A)}</span>}</td>
          <td className="mono">{B ? <>{f(B)}{sub && <span className="faint"> {sub(B)}</span>}</> : busy ? '계산 중…' : '—'}</td>
          <td className="mono" style={{ textAlign: 'right' }}>{B && (k === '현재 배치' || k === '최저 분배') ? (() => { const x = k === '현재 배치' ? B.ref - A.ref : (B.best ?? 0) - (A.best ?? 0); return <span className={x < 0 ? 'pm-down' : 'pm-up'}>{signed(x)} mW</span> })() : ''}</td></tr>)}</tbody>
      </table>
      {B?.warn.map((w) => <div key={w} className="lib-note warn" style={{ marginTop: 6 }}>{bName}: {w}</div>)}
    </Card>
  )
}

/** "가정 민감도": rerun the rebalance with each architecture assumption at its low / high value. */
export interface SensSpec { key: string; label: string; low: { label: string; patch: Record<string, unknown> }; high: { label: string; patch: Record<string, unknown> } }
export const SENS_SPECS: SensSpec[] = [
  { key: 'growth', label: 'SW 부하 증가', low: { label: '×0.9', patch: { default_growth: 0.9 } }, high: { label: '×1.2', patch: { default_growth: 1.2 } } },
  { key: 'margin', label: 'schedutil margin', low: { label: '1.15', patch: { freq_margin: 1.15 } }, high: { label: '1.35', patch: { freq_margin: 1.35 } } },
  { key: 'pg', label: 'idle power gating', low: { label: '0.80', patch: { power_gating_eff: 0.8 } }, high: { label: '0.95', patch: { power_gating_eff: 0.95 } } },
]
interface SensRow { key: string; label: string; lowLabel: string; highLabel: string; low: CpuRebalance | null; high: CpuRebalance | null }
const bestSet = (r: CpuRebalance | null) => (r?.best ? r.best.moved.map((u) => `${u}>${r.best!.assign[u]}`).sort().join('|') : '')

export function AssumptionSensitivity({ base, runVariant, dsu }: { base: CpuRebalance; runVariant: (patch: Record<string, unknown>) => Promise<CpuRebalance>; dsu: DsuPolicy | null }) {
  const [rows, setRows] = useState<SensRow[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const go = async () => {
    setBusy(true); setErr(null); setRows([])
    try {
      const out: SensRow[] = []
      const vote = dsu?.mode === 'vote' ? dsu.vote : base.dsu_model?.mode === 'vote' ? base.dsu_model.vote : undefined
      if (vote && base.dsu_params) {
        out.push({ key: 'dsu', label: 'DSU vote 표', lowLabel: '−1 step', highLabel: '+1 step',
          low: applyDsuRebalance(base, { mode: 'vote', vote: shiftVote(vote, base.dsu_params, -1) }), high: applyDsuRebalance(base, { mode: 'vote', vote: shiftVote(vote, base.dsu_params, 1) }) })
        setRows([...out])
      }
      for (const s of SENS_SPECS) {     // sequential: one simulation admission slot at a time
        const low = await runVariant(s.low.patch), high = await runVariant(s.high.patch)
        out.push({ key: s.key, label: s.label, lowLabel: s.low.label, highLabel: s.high.label, low, high })
        setRows([...out])
      }
    } catch (e) { setErr(String((e as Error).message ?? e)) } finally { setBusy(false) }
  }
  const b0 = base.best?.total_mw ?? base.reference.total_mw
  const span = Math.max(1, ...rows.flatMap((r) => [r.low, r.high].map((x) => Math.abs((x?.best?.total_mw ?? b0) - b0))))
  const ref = bestSet(base)
  return (
    <Card id="cpu-rb-sens" title="가정 민감도" defaultWide help={CPU_HELP.rbSens} minHeight={110}
      note="architecture 가정을 낮게 / 높게 바꿔 최저 전력과 권장 분배가 바뀌는지 · DSU는 즉시, 나머지는 재계산 (가정당 2회)"
      actions={<button className="btn tb-mini" disabled={busy} onClick={() => void go()}>{busy ? '계산 중…' : rows.length ? '다시 계산' : '민감도 계산'}</button>}>
      {err && <div className="err">{err}</div>}
      {!rows.length && !busy && <div className="faint" style={{ fontSize: 12 }}>기준: 최저 {fmt(b0, 1)} mW · 권장 분배 task {base.best?.moved.length ?? 0}개 이동. “민감도 계산”을 누르면 가정별로 다시 계산합니다.</div>}
      {rows.length > 0 && <table className="tb-mini-table" style={{ width: '100%' }} aria-label="가정 민감도">
        <thead><tr><th>가정</th><th style={{ textAlign: 'right' }}>낮게</th><th style={{ width: '38%' }}>최저 mW 변화 (기준 {fmt(b0, 1)})</th><th>높게</th><th>권장 분배</th></tr></thead>
        <tbody>{[...rows].sort((p, q) => Math.abs(((q.high?.best?.total_mw ?? b0) - (q.low?.best?.total_mw ?? b0))) - Math.abs(((p.high?.best?.total_mw ?? b0) - (p.low?.best?.total_mw ?? b0)))).map((r) => {
          const lo = (r.low?.best?.total_mw ?? b0) - b0, hi = (r.high?.best?.total_mw ?? b0) - b0
          const changed = [r.low, r.high].filter((x) => x && bestSet(x) !== ref).length
          const bar = (v: number, cls: string) => <span className={`sens-bar ${cls}`} style={{ width: `${(50 * Math.abs(v)) / span}%`, [v < 0 ? 'right' : 'left']: '50%' } as React.CSSProperties} />
          return <tr key={r.key}><td>{r.label}</td><td className="mono" style={{ textAlign: 'right' }}>{r.lowLabel} <span className="faint">{signed(lo)}</span></td>
            <td><div className="sens-track">{bar(lo, 'lo')}{bar(hi, 'hi')}<span className="sens-mid" /></div></td>
            <td className="mono">{r.highLabel} <span className="faint">{signed(hi)}</span></td>
            <td>{changed ? <span className="badge v-warn" title="이 가정 범위에서 최저 분배(옮길 task·cluster)가 달라짐 — 먼저 확정할 가정">바뀜 {changed}/2</span> : <span className="badge v-ok">유지</span>}</td></tr>
        })}</tbody>
      </table>}
    </Card>
  )
}

/** ① first look: concentrate on one MID cluster vs spread over 2 … N, then whether BIG would ever help. */
export function StrategyCard({ r, onPickCase }: { r: CpuRebalance; onPickCase?: (assign: Record<string, string>) => void }) {
  const s = r.strategies
  const [open, setOpen] = useState<string | null>(null)
  if (!s) return null
  const v = strategyVerdict(s)
  const rows = s.rows
  const ref = r.reference.total_mw
  const hi = Math.max(ref, ...rows.map((x) => x.total_mw), ...(s.big_check?.best ? [s.big_check.best.total_mw] : [])) * 1.05
  const pct = (mw: number) => `${Math.max(0, Math.min(100, (100 * mw) / hi))}%`
  const sym = r.symmetric.filter((g) => g.length > 1)
  const label = (x: RbStrategyRow) => x.kind === 'concentrate' ? `${x.clusters[0]}만` : `${x.clusters.map(shortCluster).join(' + ')}`
  const bestMw = Math.min(...rows.filter((x) => x.feasible).map((x) => x.total_mw))
  return (
    <Card id="cpu-rb-strategy" title="① MID 집중 vs 분산" defaultWide help={CPU_HELP.rbStrategy}
      note={`camera SW를 MID cluster 하나에 모을지, 여러 개에 나눌지 먼저 비교 · 막대 = CPU + DSU mW · 점선 = 현재 ${fmt(ref, 1)} mW${s.complete ? '' : ' · 국소 탐색'}`}>
      <div className={`lib-note ${v.tone === 'warn' ? 'warn' : ''}`} style={{ marginBottom: 8, fontSize: 13 }}><b>{v.text}</b></div>
      <div className="rb-strat">
        {(['concentrate', 'spread'] as const).map((kind) => <div key={kind} className="rb-strat-group">
          <div className="rb-strat-head">{kind === 'concentrate' ? '집중 (한 cluster)' : '분산 (여러 cluster)'}</div>
          {rows.filter((x) => x.kind === kind).map((x) => {
            const key = x.clusters.join('+')
            return <div key={key}>
              <button className={`rb-strat-row ${x.feasible ? '' : 'infeasible'} ${open === key ? 'on' : ''}`} onClick={() => setOpen(open === key ? null : key)}
                title={x.feasible ? '클릭 = task 배치' : 'budget 미충족'}>
                <span className="rb-strat-label mono">{label(x)}{x.total_mw === bestMw && x.feasible ? ' ★' : ''}</span>
                <span className="rb-strat-bar"><span style={{ width: pct(x.total_mw), background: x.feasible ? (kind === 'concentrate' ? '#8A8274' : '#2F6F68') : '#E2DBCF' }} />
                  <i style={{ left: pct(ref) }} /></span>
                <span className="mono rb-strat-mw">{fmt(x.total_mw, 1)}</span>
                <span className={`mono rb-strat-d ${x.delta_mw < 0 ? 'pm-down' : 'pm-up'}`}>{x.delta_mw >= 0 ? '+' : ''}{fmt(x.delta_mw, 1)}</span>
                <span className="faint rb-strat-mhz">{r.pool.map((c) => `${shortCluster(c)} ${x.mhz[c]}`).join(' · ')} · DSU {x.mhz.dsu}{x.feasible ? '' : ' · budget 미충족'}</span>
              </button>
              {open === key && <div className="rb-strat-detail">
                {Object.entries(x.assign).map(([u, c]) => <span key={u} className="badge" style={{ marginRight: 4 }}>{u} → {shortCluster(c)}</span>)}
                {x.min_slack_ms !== undefined && x.min_slack_ms !== null && <span className="faint"> · 최소 slack {fmt(x.min_slack_ms, 2)} ms</span>}
                {onPickCase && <button className="btn tb-mini" style={{ marginLeft: 8 }} onClick={() => onPickCase(x.assign)}>이 배치 고정 →</button>}
              </div>}
            </div>
          })}
        </div>)}
        {s.big_check && <div className="rb-strat-group">
          <div className="rb-strat-head">BIG 확인 (pool 밖, 최저 MID 분배 기준)</div>
          <div className={`lib-note ${bigVerdict(s.big_check).tone === 'warn' ? 'warn' : ''}`} style={{ fontSize: 12.5 }}>{bigVerdict(s.big_check).text}</div>
          <table className="tb-mini-table" style={{ marginTop: 4 }}>
            <thead><tr><th>옮길 task</th><th>cluster</th><th style={{ textAlign: 'right' }}>CPU+DSU mW</th><th style={{ textAlign: 'right' }}>Δ</th><th style={{ textAlign: 'right' }}>BIG MHz</th></tr></thead>
            <tbody>{s.big_check.moves.slice(0, 5).map((m) => <tr key={m.unit + m.cluster} className={m.feasible ? '' : 'faint'}>
              <td className="mono">{m.unit}</td><td>{m.cluster}</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(m.total_mw, 1)}</td>
              <td className={`mono ${m.delta_mw < 0 ? 'pm-down' : 'pm-up'}`} style={{ textAlign: 'right' }}>{m.delta_mw >= 0 ? '+' : ''}{fmt(m.delta_mw, 1)}{m.feasible ? '' : ' (미충족)'}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{m.mhz}</td></tr>)}</tbody>
          </table>
        </div>}
      </div>
      {sym.length > 0 && <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>같은 구성: {sym.map((g) => g.join(' ≡ ')).join(' · ')} — 한쪽만 표시</div>}
    </Card>
  )
}
