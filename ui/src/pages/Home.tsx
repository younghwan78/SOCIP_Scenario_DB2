import { useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { archApi } from '../lib/archExplore'
import { calibrationApi } from '../lib/calibration'
import { DOMAIN_LABEL, domainFor, type Domain } from '../lib/tunnel'
import { PipelineTunnel } from '../components/PipelineTunnel'

const quiet = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null)

export function HomePage({ ctx }: { ctx: Ctx }) {
  const item = ctx.catalog.find((c) => c.scenario_id === ctx.scenario)
  const [domain, setDomain] = useState<Domain>(() => domainFor(item?.category))
  const [paused, setPaused] = useState(false)
  const runs = useAsync(() => quiet(archApi.runs()), [])
  const reports = useAsync(() => quiet(archApi.reports()), [])
  const board = useAsync(() => quiet(archApi.board()), [])
  const meas = useAsync(() => quiet(calibrationApi.measurements()), [])
  const variants = ctx.catalog.reduce((s, c) => s + c.variant_count, 0)
  const run = runs.data?.[0]
  const report = reports.data?.[0]
  const worst = (meas.data ?? []).map((m) => m.current_prediction?.delta_pct ?? m.simulation?.delta_pct).filter((x): x is number => x !== null && x !== undefined)
  return (
    <div className="home">
      <PipelineTunnel domain={domain} paused={paused} />
      <section className="home-card" aria-label="시작">
        <div className="home-kicker">SoC MULTIMEDIA · SCENARIO DB</div>
        <h2>Pipeline 안으로<br />들어가 보세요</h2>
        <p>Multimedia scenario의 pipeline, SW timing, clock · DVFS level, power와 BW를 예측하고 architecture를 검토합니다.</p>
        <button type="button" className="home-sso" disabled title="사내 SSO 연동 예정">사내 SSO로 로그인 (연동 예정)</button>
        <a className="home-local" href={`#/explorer?scenario=${encodeURIComponent(ctx.scenario)}`}>로컬 모드로 계속 → Scenario</a>
      </section>
      <div className="home-controls">
        <div className="seg sm home-seg" role="group" aria-label="pipeline 종류">
          {(Object.keys(DOMAIN_LABEL) as Domain[]).map((d) => <button key={d} className={domain === d ? 'on' : ''} onClick={() => setDomain(d)}>{DOMAIN_LABEL[d]}</button>)}
        </div>
        <button type="button" className="home-pill" onClick={() => setPaused((p) => !p)}>{paused ? '애니메이션 재생' : '애니메이션 멈춤'}</button>
      </div>
      <section className="home-stats" aria-label="현황">
        <a className="home-stat" href="#/explorer"><span>Scenario · variant</span><b>{ctx.catalog.length} · {variants}</b></a>
        <a className="home-stat" href="#/predictions"><span>Current 예측</span><b>{board.data ? board.data.rows.length : '—'}</b></a>
        <a className="home-stat wide" href={run ? `#/explore?run=${encodeURIComponent(run.id)}` : '#/explore'}>
          <span>최근 탐색 run</span><b className="txt">{run ? `${run.title} · ${run.summary.spec_ok}/${run.summary.variants} 만족` : '없음'}</b></a>
        <a className="home-stat wide" href={report ? `#/reports?report=${encodeURIComponent(report.id)}` : '#/reports'}>
          <span>최근 검토 보고서</span><b className="txt">{report ? report.scenario_type : '없음'}</b></a>
        <a className="home-stat" href="#/calibration"><span>예측 ↔ 실측</span><b>{meas.data ? `${meas.data.length}건` : '—'}</b>
          {worst.length > 0 && <em>최대 |Δ| {Math.max(...worst.map(Math.abs)).toFixed(1)}%</em>}</a>
      </section>
    </div>
  )
}
