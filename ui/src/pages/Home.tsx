import { useMemo, useState, type CSSProperties } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { getJson } from '../lib/api'
import { experimentHref, listExperimentContexts } from '../lib/experimentContext'
import { CATEGORY_COLOR, CATEGORY_LABEL, CATEGORY_ORDER, primaryCategory } from '../lib/guides'
import { DOMAIN_LABEL, domainFor, type Domain } from '../lib/tunnel'
import { PipelineTunnel } from '../components/PipelineTunnel'

import { projLabel, socLabel } from '../lib/projects'

interface Overview {
  counts: { ip: number; dvfs: number; dvfs_sample: number; predictions: number; runs: number; reports: number; published_reports: number; measurements: number; synthetic_measurements: number }
  coverage: { simulation: number; measurement: number; synthetic: number; unknown?: number; current_prediction: number }
  latest_run: { id: string; title: string; created_at: string; summary: { spec_ok: number; variants: number } } | null
  latest_report: { id: string; status: string; created_at: string } | null
}

export function HomePage({ ctx }: { ctx: Ctx }) {
  const item = ctx.catalog.find((c) => c.scenario_id === ctx.scenario)
  const [domain, setDomain] = useState<Domain>(() => domainFor(item?.category))
  const [paused, setPaused] = useState(false)
  const overview = useAsync(() => getJson<Overview>('/explorer/overview', { project_ref: ctx.project || undefined }), [ctx.project])
  const recent = listExperimentContexts().filter((e) => e.scope.project_ref === ctx.project).slice(0, 3)
  const scope = { project_ref: ctx.project, scenario_id: ctx.scenario, variant_id: ctx.variant }

  // project (SoC 과제) × scenario type → scenario / variant counts
  const matrix = useMemo(() => {
    const projects = new Map<string, { soc: string; cells: Map<string, { sc: number; v: number }>; sc: number; v: number }>()
    for (const c of ctx.allCatalog) {
      const p = projects.get(c.project_id) ?? { soc: socLabel(c.soc_ref), cells: new Map(), sc: 0, v: 0 }
      const cat = primaryCategory(c.category)
      const cell = p.cells.get(cat) ?? { sc: 0, v: 0 }
      cell.sc += 1; cell.v += c.variant_count
      p.cells.set(cat, cell); p.sc += 1; p.v += c.variant_count
      projects.set(c.project_id, p)
    }
    const cats = (CATEGORY_ORDER as readonly string[]).filter((k) => [...projects.values()].some((p) => p.cells.has(k)))
    const extra = [...new Set([...projects.values()].flatMap((p) => [...p.cells.keys()]))].filter((k) => !cats.includes(k))
    return { projects: [...projects.entries()], cats: [...cats, ...extra] }
  }, [ctx.allCatalog])

  const variants = ctx.catalog.reduce((s, c) => s + c.variant_count, 0)
  const sum = (k: 'simulation' | 'measurement' | 'synthetic' | 'current_prediction') => overview.data?.coverage[k] ?? 0
  const run = overview.data?.latest_run
  const report = overview.data?.latest_report
  const sampleDvfs = overview.data?.counts.dvfs_sample ?? 0
  const pct = (n: number) => (variants ? Math.round((100 * n) / variants) : 0)

  return (
    <div className="home">
      <PipelineTunnel domain={domain} paused={paused} />
      <section className="home-card" aria-label="시작">
        <div className="home-kicker">SoC MULTIMEDIA · SCENARIO DB</div>
        <h2>조건을 바꾸고<br />차이를 확인하세요</h2>
        <p>기준 scenario를 고정해 IP mode, 처리 크기, 센서를 바꾸고 성능·전력·근거를 비교합니다.</p>
        <div className="home-experiment-actions">{[['ip_mode', 'IP 모드'], ['chain_size', '크기 · crop'], ['sensor_mode', '센서']].map(([target, label]) => <a key={target} className="btn" href={`${experimentHref('whatif', scope)}&whatif_target=${target}`}>{label} 변경</a>)}</div>
        <a className="home-local" href={`#/explorer?project=${encodeURIComponent(ctx.project)}&scenario=${encodeURIComponent(ctx.scenario)}`}>기준 Scenario 선택 →</a>
        {recent.length > 0 && <div className="home-recent"><b>최근 실험 이어하기</b>{recent.map((e) => <a key={`${e.scope.scenario_id}:${e.scope.variant_id}`} href={experimentHref('whatif', e.scope)}>{e.scope.variant_id} · 후보 {e.candidates.length}개</a>)}</div>}
      </section>
      <div className="home-controls">
        <div className="seg sm home-seg" role="group" aria-label="pipeline 종류">
          {(Object.keys(DOMAIN_LABEL) as Domain[]).map((d) => <button key={d} className={domain === d ? 'on' : ''} onClick={() => setDomain(d)}>{DOMAIN_LABEL[d]}</button>)}
        </div>
        <button type="button" className="home-pill" onClick={() => setPaused((p) => !p)}>{paused ? '애니메이션 재생' : '애니메이션 멈춤'}</button>
      </div>

      <section className="home-dock" aria-label="현황">
        <div className="hd-block hd-wide">
          <h3>과제 × Scenario type <span>scenario · variant · 과제명을 눌러 선택</span></h3>
          <table className="hd-matrix">
            <thead><tr><th>SoC · 과제</th>
              {matrix.cats.map((c) => <th key={c} style={{ '--cat': CATEGORY_COLOR[c] ?? CATEGORY_COLOR.other } as CSSProperties}>
                <a href={`#/explorer?type=${c}&project=${encodeURIComponent(ctx.project)}`}><i />{CATEGORY_LABEL[c] ?? c}</a></th>)}
              <th>합계</th></tr></thead>
            <tbody>{matrix.projects.map(([pid, p]) => (
              <tr key={pid} className={`proj-row ${pid === ctx.project ? 'on' : ''}`}>
                <td><button type="button" className="proj-open" onClick={() => ctx.setProject(pid)} title="이 과제로 Scenario 열기"><b>{p.soc}</b> · {projLabel(pid)}</button></td>
                {matrix.cats.map((c) => { const cell = p.cells.get(c); return <td key={c} className="n">{cell ? <>{cell.sc} · <span>{cell.v}</span></> : '—'}</td> })}
                <td className="n"><b>{p.sc} · {p.v}</b></td></tr>))}
            </tbody>
          </table>
        </div>
        <a className="hd-block" href={experimentHref('calibration', scope)}>
          <h3>선택 과제 근거 coverage <span>variant {variants}개 중</span></h3>
          {overview.data ? <>
            <Meter label="Simulation 예측" n={sum('simulation')} pct={pct(sum('simulation'))} color="#56B4E9" />
            <Meter label="등록 예측 (current)" n={sum('current_prediction')} pct={pct(sum('current_prediction'))} color="#2BB3A3" />
            {(overview.data.coverage.unknown ?? 0) > 0 && <p className="hd-em">출처 미상 {overview.data.coverage.unknown} variant — 실측 coverage에서 제외</p>}
            <Meter label="실측" n={sum('measurement')} pct={pct(sum('measurement'))} color="#7FD6C8" note={sum('synthetic') ? `+ 합성 ${sum('synthetic')}` : undefined} />
          </> : <p className="hd-dim">{overview.error ? '현황을 불러오지 못했습니다' : '현황 불러오는 중…'}</p>}
          <p className="hd-dim">구성별 오차와 실제 측정 근거 확인 →</p>
        </a>
        <div className="hd-block">
          <h3>Architecture 검토</h3>
          <a className="hd-row" href={experimentHref('predictions', scope)}><span>등록 예측</span><b>{overview.data?.counts.predictions ?? '—'}</b></a>
          <a className="hd-row" href={`${experimentHref('explore', scope)}${run ? `&run=${encodeURIComponent(run.id)}` : ''}`}><span>최근 탐색</span>
            <b className="txt" title={run?.title}>{run ? `${run.summary.spec_ok}/${run.summary.variants} 만족 · ${run.created_at?.slice(5, 10) ?? ''}` : '없음'}</b></a>
          <a className="hd-row" href={`${experimentHref('reports', scope)}${report ? `&report=${encodeURIComponent(report.id)}` : ''}`}><span>보고서</span>
            <b className="txt">{overview.data ? `${overview.data.counts.reports}건 · 게시 ${overview.data.counts.published_reports}` : '—'}{report ? ` · 최근 ${report.status}` : ''}</b></a>
        </div>
        <a className="hd-block" href={experimentHref('library', scope)}>
          <h3>Library</h3>
          <div className="hd-row"><span>DVFS table</span><b>{overview.data?.counts.dvfs ?? '—'}</b></div>
          {sampleDvfs > 0 && <p className="hd-em">SAMPLE/SYNTHETIC {sampleDvfs} — 사내 table 교체 필요</p>}
          {overview.data?.counts.dvfs === 0 && <p className="hd-em">DVFS 미연결 — level·전압 산출 불가</p>}
          <div className="hd-row"><span>IP catalog</span><b>{overview.data?.counts.ip ?? '—'}</b></div>
        </a>
      </section>
    </div>
  )
}

function Meter({ label, n, pct, color, note }: { label: string; n: number; pct: number; color: string; note?: string }) {
  return (
    <div className="hd-meter">
      <div className="hd-row"><span>{label}</span><b>{n} <small>({pct}%)</small>{note && <em> {note}</em>}</b></div>
      <div className="hd-bar"><i style={{ width: `${Math.min(100, pct)}%`, background: color }} /></div>
    </div>
  )
}
