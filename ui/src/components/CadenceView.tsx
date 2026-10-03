import { useMemo, type ReactNode } from 'react'
import type { ViewResponse } from '../lib/api'
import { analyse, frameWindows, type CadenceResult, type Verdict } from '../lib/cadence'
import { frameSliceStyle, type Timeline } from '../lib/timeline'
import type { ModeNote } from '../lib/modes'
import { LANE_LABEL, LANE_ORDER, type Lane } from '../lib/model'
import { BoxPlot, SERIES, useWidth } from './Charts'
import { useTip } from './ChartTip'

const VERDICT: Record<Verdict, { label: string; cls: string }> = {
  ok: { label: 'fps 충족', cls: 'v-ok' }, warn: { label: '주의', cls: 'v-warn' }, fail: { label: 'fps 미달', cls: 'v-fail' }, na: { label: '판정 불가', cls: 'v-na' },
}
const LANE_GROUP: Record<string, string> = { sensor: 'SENSOR', rt: 'RT', nrt: 'NRT', m2m: 'M2M', sw: 'SW', codec: 'CODEC', display: 'DISPLAY', other: 'SW' }
const LANE_COLOR: Record<string, string> = { sensor: '#94A3B8', rt: '#F4A06B', sw: '#E2C15B', nrt: '#E07B39', m2m: '#C9A27E', codec: '#A78BCA', display: '#6CB8A8', other: '#C4BBAE' }

/** Frame pipeline Gantt: one row per frame, bars per lane window → RT(N+1) ∥ NRT/Output(N) overlap. */
function FramePipeline({ windows, period, colorBy = 'group', onPick, picked }: {
  windows: ReturnType<typeof frameWindows>; period: number | null; colorBy?: 'group' | 'frame'
  onPick?: (frame: number, lane: string) => void; picked?: { frame: number; lane: string } | null
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const tip = useTip()
  if (!windows.length) return <div className="empty">frame별 stage 정보 없음</div>
  const frames = [...new Set(windows.map((w) => w.frame))].sort((a, b) => a - b)
  const t0 = Math.min(...windows.map((w) => w.start)), t1 = Math.max(...windows.map((w) => w.end))
  const LW = 44, RH = 22, plotW = Math.max(200, width - LW - 16)
  const x = (t: number) => LW + ((t - t0) / (t1 - t0 || 1)) * plotW
  const lanes = LANE_ORDER.filter((l) => windows.some((w) => w.lane === l))
  const vsync = period ? Array.from({ length: Math.floor((t1 - t0) / period) + 1 }, (_, i) => t0 + i * period) : []
  return (
    <div ref={ref} style={{ width: '100%' }}>
      <div className="legend-row">{colorBy === 'group' && lanes.map((l) => <span key={l} className="legend-item"><span className="sw" style={{ background: LANE_COLOR[l] }} />{LANE_LABEL[l as Lane]}</span>)}
        {colorBy === 'frame' && <span className="legend-item faint">색 = frame × 분류 (위 범례) · 행 = frame</span>}
        {period && <span className="legend-item faint">┆ = sensor period {period.toFixed(2)} ms</span>}
        {onPick && <span className="legend-item faint">막대 클릭 = 그 frame·stage의 첫 slice 선택 (그래프·상세 연동)</span>}</div>
      <svg width={width} height={frames.length * RH + 24} style={{ display: 'block' }}>
        {vsync.map((t, i) => <line key={i} x1={x(t)} y1={0} x2={x(t)} y2={frames.length * RH} stroke="#CFC6B8" strokeDasharray="2 3" />)}
        {frames.map((f, i) => (
          <g key={f}>
            <text x={4} y={i * RH + 15} fontSize={10.5} fontFamily="var(--mono)" fill="var(--muted)">f{f}</text>
            <line x1={LW} y1={i * RH + RH} x2={LW + plotW} y2={i * RH + RH} stroke="#F1ECE4" />
            {windows.filter((w) => w.frame === f).map((w) => (
              <rect key={w.lane} x={x(w.start)} y={i * RH + 4 + (LANE_ORDER.indexOf(w.lane as Lane) % 2) * 2} width={Math.max(1.5, x(w.end) - x(w.start))} height={RH - 10} rx={2}
                {...(() => { const st = frameSliceStyle(f, LANE_GROUP[w.lane] ?? 'SW'); const on = picked?.frame === f && picked?.lane === w.lane
                  return colorBy === 'frame' ? { fill: st.fill, stroke: on ? '#1F2430' : st.stroke, strokeWidth: on ? 2 : 0.8, strokeDasharray: st.dash } : { fill: LANE_COLOR[w.lane] ?? '#ccc', stroke: on ? '#1F2430' : 'none', strokeWidth: on ? 2 : 0 } })()}
                opacity={0.9} style={onPick ? { cursor: 'pointer' } : undefined} onClick={onPick ? () => onPick(f, w.lane) : undefined}
                {...tip(() => {
                  const f0 = windows.filter((x) => x.frame === f)
                  const origin = Math.min(...f0.map((x) => x.start))
                  return { title: `f${f} · ${LANE_LABEL[w.lane as Lane] ?? w.lane}`, color: LANE_COLOR[w.lane],
                    head: { label: '구간 길이', value: `${(w.end - w.start).toFixed(2)} ms`, tone: 'strong' as const },
                    rows: [{ k: '시작 (frame 시작 기준)', v: `+${(w.start - origin).toFixed(2)} ms` }, { k: '종료 (frame 시작 기준)', v: `+${(w.end - origin).toFixed(2)} ms` },
                      ...(period ? [{ k: '주기 대비', v: `${(((w.end - w.start) / period) * 100).toFixed(0)}% of ${period.toFixed(2)} ms`, tone: (w.end - w.start > period ? 'bad' : undefined) as 'bad' | undefined }] : []),
                      { k: '절대 시각', v: `${w.start.toFixed(2)} – ${w.end.toFixed(2)} ms`, tone: 'muted' as const }] }
                })} />
            ))}
          </g>
        ))}
        <text x={LW} y={frames.length * RH + 16} fontSize={9.5} fill="var(--muted)" fontFamily="var(--mono)">{t0.toFixed(1)} ms</text>
        <text x={LW + plotW} y={frames.length * RH + 16} fontSize={9.5} textAnchor="end" fill="var(--muted)" fontFamily="var(--mono)">{t1.toFixed(1)} ms</text>
      </svg>
    </div>
  )
}

/** max overlap between RT(f+1) and any non-RT window of frame f */
export function rtOverlapOf(windows: ReturnType<typeof frameWindows>): number {
  let best = 0
  for (const w of windows) {
    if (w.lane !== 'rt') continue
    for (const p of windows) if (p.frame === w.frame - 1 && p.lane !== 'rt' && p.lane !== 'sensor') best = Math.max(best, Math.min(w.end, p.end) - Math.max(w.start, p.start))
  }
  return best
}

/** One context line shared by every Timing view (trace / 주기·지연 / 비교) so switching views keeps the frame of reference. */
export function TimingContextStrip({ timeline, view, fps, laneOfPid, notes, extra }: {
  timeline: Timeline; view?: ViewResponse; fps: number | null; laneOfPid: (pid: string) => string | undefined; notes: ModeNote[]; extra?: ReactNode
}) {
  const a = useMemo(() => analyse(timeline, view, fps), [timeline, view, fps])
  const overlap = useMemo(() => rtOverlapOf(frameWindows(timeline, laneOfPid)), [timeline, laneOfPid])
  return (
    <div className="cad-note timing-ctx">
      {a.period && <span className="chip">target {fps} fps · {a.period.toFixed(2)} ms</span>}
      <span className="chip">frame {timeline.frames.length}</span>
      <span className="chip" title="동시에 처리 중인 frame 수 최대값">in-flight 최대 {a.inFlight} frame</span>
      {overlap > 0 && <span className="chip" title="RT(N+1)과 NRT/Output(N)이 겹친 최대 시간">RT(N+1) ∥ N 후단 {overlap.toFixed(1)} ms</span>}
      {notes.map((n) => <span key={n.id} className={`chip mode-${n.tone}`} title={n.detail}>{n.label}</span>)}
      {extra}
    </div>
  )
}

export function CadenceView({ timeline, view, fps, laneOfPid, colorBy = 'group', onPick, picked }: {
  timeline: Timeline; view?: ViewResponse; fps: number | null; laneOfPid: (pid: string) => string | undefined
  colorBy?: 'group' | 'frame'; onPick?: (frame: number, lane: string) => void; picked?: { frame: number; lane: string } | null
}) {
  const a = useMemo(() => analyse(timeline, view, fps), [timeline, view, fps])
  const windows = useMemo(() => frameWindows(timeline, laneOfPid), [timeline, laneOfPid])
  const outs = a.results.filter((r) => r.stream.kind !== 'input')
  const card = (r: CadenceResult, i: number) => {
    const v = VERDICT[r.verdict]
    return (
      <div key={r.stream.id} className="cad-card" style={{ borderTopColor: SERIES[i % SERIES.length] }}>
        <div className="cad-h"><span>{r.stream.label}</span><span className={`badge ${v.cls}`}>{r.batch ? 'batch' : v.label}</span></div>
        <div className="cad-big mono">{r.fpsAchieved ? r.fpsAchieved.toFixed(2) : '—'}<small> fps</small>{fps ? <small className="faint"> / {fps}</small> : null}</div>
        <div className="cad-kv mono">
          <span>평균 interval</span><span><b>{r.box ? r.box.mean.toFixed(2) : '—'}</b> ms</span>
          <span className="faint">min – max</span><span className="faint">{r.box ? `${r.box.min.toFixed(2)} – ${r.box.max.toFixed(2)}` : '—'} ms</span>
          <span>jitter σ</span><span>{r.box ? r.box.std.toFixed(3) : '—'} ms</span>
          <span>평균 latency</span><span><b>{r.latBox ? r.latBox.mean.toFixed(1) : '—'}</b> ms</span>
          <span className="faint">max latency</span><span className="faint">{r.latBox ? r.latBox.max.toFixed(1) : '—'} ms</span>
          <span>drop</span><span>{a.period ? r.drops : '—'}{r.batch ? ' · burst+gap' : ''}</span>
        </div>
      </div>
    )
  }
  return (
    <div className="cad">
      <div className="cad-cards">{outs.map(card)}</div>
      <h4 className="cad-title">출력 buffer 간격 분포 <span className="faint">— 점선 = target period, 음영 = ±5%, ◇ = 평균</span></h4>
      <BoxPlot rows={a.results.map((r, i) => ({ id: r.stream.id, label: r.stream.label, box: r.box, values: r.intervals, tipTitle: `${r.stream.label} · 출력 간격`, color: r.stream.kind === 'input' ? '#94A3B8' : SERIES[i % SERIES.length] }))}
        target={a.period} targetLabel={a.period ? `${a.period.toFixed(2)} ms (${fps} fps)` : undefined} />
      <h4 className="cad-title">Sensor frame start → 출력 지연</h4>
      <BoxPlot rows={outs.map((r, i) => ({ id: r.stream.id, label: r.stream.label, box: r.latBox, values: r.latencies, tipTitle: `${r.stream.label} · sensor → 출력 지연`, color: SERIES[i % SERIES.length] }))} />
      <h4 className="cad-title">Frame pipeline <span className="faint">— frame별 stage 구간 · 세로 점선 = sensor 주기 · RT(N+1)이 N의 NRT/Output과 겹치는지 확인</span></h4>
      <FramePipeline windows={windows} period={a.period} colorBy={colorBy} onPick={onPick} picked={picked} />
      {timeline.frames.length < 4 && <div className="faint" style={{ fontSize: 12, marginTop: 8 }}>frame 수가 적어 분포 신뢰도가 낮습니다. 긴 trace(≥ 30 frame)를 import하면 box plot이 의미 있어집니다.</div>}
    </div>
  )
}
