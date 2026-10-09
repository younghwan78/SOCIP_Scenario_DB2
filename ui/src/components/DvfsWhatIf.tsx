// Timing Budget ⑦: each DVFS domain pinned one / two levels faster or slower — SW slack, power, BW, verdict.
import { Fragment, useState } from 'react'
import { fmt, verdictChip, STAGE_COLOR, type DvfsComboRow, type DvfsWhatIf, type StageId } from '../lib/timingBudget'
import { maText, type Battery } from '../lib/battery'

const STAGE_SHORT: Record<StageId, string> = { rt: 'RT', nrt: 'NRT', post: 'Post', output: 'Out' }
const signed = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(d)}`)
const gbs = (v: number | null | undefined) => (v === null || v === undefined ? '—' : (v / 1000).toFixed(2))

/** Label of a multi-domain combo: '*' presets read as "모든 domain −1". */
export function comboLabel(c: DvfsComboRow, nDomains: number): string {
  const ks = Object.values(c.combo)
  const uniform = ks.length > 0 && ks.every((k) => k === ks[0])
  const head = uniform && ks.length === nDomains && nDomains > 1 ? `모든 domain ${ks[0] > 0 ? '+' : '−'}${Math.abs(ks[0])}` : Object.entries(c.combo).map(([g, k]) => `${g} ${k > 0 ? '+' : '−'}${Math.abs(k)}`).join(' + ')
  return c.label ? `${head} (${c.label})` : head
}

export function DvfsWhatIfTable({ data, battery }: { data: DvfsWhatIf; battery: Battery }) {
  const [only, setOnly] = useState<string>('')
  const stages: StageId[] = ['rt', 'nrt', 'post', 'output']
  const base = data.base
  const domains = data.domains.filter((d) => !only || d.domain === only)
  return <div>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6, fontSize: 12 }}>
      <span className="faint">기준: {fmt(base.total_mw, 0)} mW ({maText(base.total_mw, battery)}@Vbat) · {fmt(base.bw_mbs / 1000, 2)} GB/s · SW 여유 {stages.map((s) => `${STAGE_SHORT[s]} ${fmt(base.slack_ms[s], 1)}`).join(' · ')} ms</span>
      <span className="grow" />
      <div className="seg sm" role="group" aria-label="domain">
        <button className={!only ? 'on' : ''} onClick={() => setOnly('')}>전체</button>
        {data.domains.map((d) => <button key={d.domain} className={only === d.domain ? 'on' : ''} onClick={() => setOnly(d.domain)}>{d.domain}</button>)}
      </div>
    </div>
    <div className="table-x">
      <table className="tb-mini-table dvfs-wi" style={{ width: '100%' }}>
        <thead><tr><th>Domain</th><th>Level</th><th style={{ textAlign: 'right' }}>MHz</th><th>판정</th>
          <th style={{ textAlign: 'right' }}>ΔPower mW</th><th style={{ textAlign: 'right' }}>ΔmA@Vbat</th><th style={{ textAlign: 'right' }}>IP · BW mW</th>
          <th style={{ textAlign: 'right' }} title="Peak = 가장 큰 stage가 HW 구간 동안 내는 순간 BW (평균 × period / HW 시간). 기준 대비 변화">Peak BW Δ MB/s</th>
          {stages.map((s) => <th key={s} style={{ textAlign: 'right', color: STAGE_COLOR[s] }} title="SW가 더 쓸 수 있는 시간 (현재 clock 기준) · 괄호 = 기준 대비 변화">{STAGE_SHORT[s]} 여유 ms</th>)}
          <th style={{ textAlign: 'right' }}>Video latency</th></tr></thead>
        <tbody>{domains.map((d) => {
          const rows = data.rows.filter((r) => r.domain === d.domain).sort((a, b) => a.shift - b.shift)
          const cells = [...rows.filter((r) => r.shift < 0), null, ...rows.filter((r) => r.shift > 0)]
          return <Fragment key={d.domain}>
            {cells.map((r) => {
              if (r === null) return <tr key={`${d.domain}-base`} className="dvfs-base"><td><b>{d.domain}</b> <span className="faint" style={{ fontSize: 11 }}>{d.stages.map((s) => STAGE_SHORT[s]).join('·')} · {d.ips.length} IP</span></td>
                <td className="mono">L{d.level} (현재)</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(d.mhz, 0)}</td><td><span className={`badge ${verdictChip(base.verdict).cls}`}>{verdictChip(base.verdict).label}</span></td>
                <td className="mono" style={{ textAlign: 'right' }}>{fmt(base.total_mw, 0)}</td><td className="mono" style={{ textAlign: 'right' }}>{maText(base.total_mw, battery)}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{fmt(base.hw_mw, 0)} · {fmt(base.bw_mw, 0)}</td>
                <td className="mono faint" style={{ textAlign: 'right' }} title="기준 peak stage BW (GB/s)">{gbs(base.peak_stage_mbs)} GB/s</td>
                {stages.map((s) => <td key={s} className="mono" style={{ textAlign: 'right' }}>{fmt(base.slack_ms[s], 1)}</td>)}
                <td className="mono" style={{ textAlign: 'right' }}>{fmt(base.latency_ms.video_ms, 1)}</td></tr>
              if (r.error) return <tr key={`${d.domain}${r.shift}`} className="dvfs-bound"><td className="faint" style={{ fontSize: 11 }}>{r.shift > 0 ? `${r.shift}단계 올림 ▲` : `${-r.shift}단계 내림 ▼`}</td>
                <td>{r.boundary ? <span className="badge v-info" title="DVFS table 경계 — 더 내릴/올릴 level 없음">{r.boundary}</span> : <span className="mono">{r.level !== null ? `L${r.level}` : '—'}</span>}</td>
                <td colSpan={11} className="faint">{r.error}</td></tr>
              const v = verdictChip(r.verdict ?? 'fail')
              return <tr key={`${d.domain}${r.shift}`} className={r.verdict === 'fail' ? 'dvfs-fail' : ''} title={(r.reasons ?? []).join('\n')}>
                <td className="faint" style={{ fontSize: 11 }}>{r.shift > 0 ? `${r.shift}단계 올림 ▲` : `${-r.shift}단계 내림 ▼`}</td>
                <td className="mono">L{r.level}</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(r.mhz, 0)}</td>
                <td><span className={`badge ${v.cls}`}>{v.label}</span></td>
                <td className={`mono ${(r.delta_mw ?? 0) < 0 ? 'pm-down' : 'pm-up'}`} style={{ textAlign: 'right' }}>{signed(r.delta_mw, 1)}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{maText(r.delta_mw, battery, true)}</td>
                <td className="mono faint" style={{ textAlign: 'right' }}>{signed(r.delta_hw_mw, 0)} · {signed(r.delta_bw_mw, 0)}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{signed(r.delta_peak_mbs, 0)}</td>
                {stages.map((s) => { const dv = r.delta_slack_ms?.[s] ?? 0; const v2 = r.slack_ms?.[s]; return <td key={s} className="mono" style={{ textAlign: 'right' }}>
                  <span style={{ color: v2 !== undefined && v2 < 0 ? 'var(--del-text)' : undefined }}>{fmt(v2 ?? null, 1)}</span>
                  {Math.abs(dv) > 0.005 && <span className={dv > 0 ? 'pm-down' : 'pm-up'} style={{ fontSize: 10.5 }}> ({signed(dv, 1)})</span>}</td> })}
                <td className="mono" style={{ textAlign: 'right' }}>{fmt(r.latency_ms?.video_ms ?? null, 1)}</td>
              </tr>
            })}
          </Fragment>
        })}</tbody>
      </table>
    </div>
    {(data.combos?.length ?? 0) > 0 && <ComboTable data={data} battery={battery} />}
    <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>
      각 행 = 그 domain만 level을 고정하고 Timing Budget 전체를 다시 계산 (다른 domain은 자동). 여유 = 현재 clock에서 SW가 더 쓸 수 있는 시간
      ({data.throughput_model === 'pipelined' ? 'NRT·Post: frame period − 가장 긴 SW task (pipeline)' : 'NRT·Post: frame period − (SW + HW)'} · RT·Output: HW 예산 − HW).
      RT는 sensor readout에 묶여 clock을 올려도 여유가 늘지 않습니다. 내림이 “fail”이면 그 level에서는 처리량을 못 맞춤.
      IP clock level은 IP core power(V²·f)만 바꾸고 DMA traffic(MB/s)은 그대로 — BW 변화는 compression · buffer 크기 쪽(조합 탐색)에서 봅니다 (MIF DVFS 미모델).
      BW는 frame 평균(MB/s) 기준으로 power를 계산합니다. Peak BW = stage가 HW 구간에 몰아 쓰는 순간 BW — clock을 올리면 HW 시간이 줄어 peak가 커지고, 내리면 작아집니다
      (기준 peak {gbs(data.base.peak_stage_mbs)} GB/s · 모든 stage 동시 상한 {gbs(data.base.peak_upper_mbs)} GB/s · 평균 {gbs(data.base.bw_mbs)} GB/s).
    </div>
  </div>
}

function ComboTable({ data, battery }: { data: DvfsWhatIf; battery: Battery }) {
  const stages: StageId[] = ['rt', 'nrt', 'post', 'output']
  return <div style={{ marginTop: 10 }}>
    <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>여러 domain 동시 변경 <span className="faint" style={{ fontWeight: 400 }}>— domain끼리 서로 영향(공유 stage)을 포함해 다시 계산</span></div>
    <div className="table-x">
      <table className="tb-mini-table dvfs-combo" style={{ width: '100%' }}>
        <thead><tr><th>조합</th><th>판정</th><th style={{ textAlign: 'right' }}>ΔPower mW</th><th style={{ textAlign: 'right' }}>ΔmA@Vbat</th><th style={{ textAlign: 'right' }}>IP · BW mW</th>
          <th style={{ textAlign: 'right' }}>Peak BW Δ MB/s</th>
          {stages.map((s) => <th key={s} style={{ textAlign: 'right', color: STAGE_COLOR[s] }}>{STAGE_SHORT[s]} 여유 ms</th>)}</tr></thead>
        <tbody>{(data.combos ?? []).map((c, i) => {
          const name = comboLabel(c, data.domains.length)
          if (c.error) return <tr key={i} className="dvfs-bound"><td>{name}</td><td>{c.boundary ? <span className="badge v-info">{c.boundary}</span> : <span className="badge v-fail">오류</span>}</td><td colSpan={9} className="faint">{c.error}</td></tr>
          const v = verdictChip(c.verdict ?? 'fail')
          return <tr key={i} className={c.verdict === 'fail' ? 'dvfs-fail' : ''} title={(c.reasons ?? []).join('\n')}>
            <td style={{ fontSize: 12 }}>{name}</td><td><span className={`badge ${v.cls}`}>{v.label}</span></td>
            <td className={`mono ${(c.delta_mw ?? 0) < 0 ? 'pm-down' : 'pm-up'}`} style={{ textAlign: 'right' }}>{signed(c.delta_mw, 1)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{maText(c.delta_mw, battery, true)}</td>
            <td className="mono faint" style={{ textAlign: 'right' }}>{signed(c.delta_hw_mw, 0)} · {signed(c.delta_bw_mw, 0)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{signed(c.delta_peak_mbs, 0)}</td>
            {stages.map((s) => <td key={s} className="mono" style={{ textAlign: 'right', color: (c.slack_ms?.[s] ?? 0) < 0 ? 'var(--del-text)' : undefined }}>{fmt(c.slack_ms?.[s] ?? null, 1)}</td>)}
          </tr>
        })}</tbody>
      </table>
    </div>
  </div>
}
