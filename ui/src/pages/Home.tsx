import { useMemo, useState, type CSSProperties } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { archApi } from '../lib/archExplore'
import { calibrationApi } from '../lib/calibration'
import { libraryApi } from '../lib/library'
import { CATEGORY_COLOR, CATEGORY_LABEL, CATEGORY_ORDER, primaryCategory } from '../lib/guides'
import { DOMAIN_LABEL, domainFor, type Domain } from '../lib/tunnel'
import { PipelineTunnel } from '../components/PipelineTunnel'

const quiet = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null)
const socLabel = (s?: string | null) => (s ?? '').replace(/^soc-/, '').replace(/^exynos/i, 'Exynos') || 'SoC 미정'
const projLabel = (p: string) => p.replace(/^proj-/, '').toUpperCase()

export function HomePage({ ctx }: { ctx: Ctx }) {
  const item = ctx.catalog.find((c) => c.scenario_id === ctx.scenario)
  const [domain, setDomain] = useState<Domain>(() => domainFor(item?.category))
  const [paused, setPaused] = useState(false)
  const runs = useAsync(() => quiet(archApi.runs()), [])
  const reports = useAsync(() => quiet(archApi.reports()), [])
  const board = useAsync(() => quiet(archApi.board()), [])
  const meas = useAsync(() => quiet(calibrationApi.measurements()), [])
  const cov = useAsync(() => quiet(calibrationApi.coverageSummary()), [])
  const dvfs = useAsync(() => quiet(libraryApi.dvfs()), [])
  const ips = useAsync(() => quiet(libraryApi.ips()), [])

  // project (SoC 과제) × scenario type → scenario / variant counts
  const matrix = useMemo(() => {
    const projects = new Map<string, { soc: string; cells: Map<string, { sc: number; v: number }>; sc: number; v: number }>()
    for (const c of ctx.catalog) {
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
  }, [ctx.catalog])

  const variants = ctx.catalog.reduce((s, c) => s + c.variant_count, 0)
  const sum = (k: 'simulation' | 'measurement' | 'synthetic' | 'current_prediction') => Object.values(cov.data ?? {}).reduce((s, r) => s + (r[k] ?? 0), 0)
  const run = runs.data?.[0]
  const report = reports.data?.[0]
  const published = (reports.data ?? []).filter((r) => r.status === 'published').length
  const realMeas = (meas.data ?? []).filter((m) => !m.synthetic)
  const worst = realMeas.map((m) => m.current_prediction?.delta_pct ?? m.simulation?.delta_pct).filter((x): x is number => x !== null && x !== undefined)
  const sampleDvfs = (dvfs.data?.items ?? []).filter((t) => /sample|synthetic/i.test(`${t.id} ${JSON.stringify(t.source ?? '')}`)).length
  const pct = (n: number) => (variants ? Math.round((100 * n) / variants) : 0)

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

      <section className="home-dock" aria-label="현황">
        <div className="hd-block hd-wide">
          <h3>과제 × Scenario type <span>scenario · variant</span></h3>
          <table className="hd-matrix">
            <thead><tr><th>SoC · 과제</th>
              {matrix.cats.map((c) => <th key={c} style={{ '--cat': CATEGORY_COLOR[c] ?? CATEGORY_COLOR.other } as CSSProperties}>
                <a href={`#/explorer?type=${c}`}><i />{CATEGORY_LABEL[c] ?? c}</a></th>)}
              <th>합계</th></tr></thead>
            <tbody>{matrix.projects.map(([pid, p]) => (
              <tr key={pid}><td><b>{p.soc}</b> · {projLabel(pid)}</td>
                {matrix.cats.map((c) => { const cell = p.cells.get(c); return <td key={c} className="n">{cell ? <>{cell.sc} · <span>{cell.v}</span></> : '—'}</td> })}
                <td className="n"><b>{p.sc} · {p.v}</b></td></tr>))}
            </tbody>
          </table>
        </div>
        <a className="hd-block" href="#/calibration">
          <h3>근거 coverage <span>variant {variants}개 중</span></h3>
          {cov.data ? <>
            <Meter label="Simulation 예측" n={sum('simulation')} pct={pct(sum('simulation'))} color="#56B4E9" />
            <Meter label="등록 예측 (current)" n={sum('current_prediction')} pct={pct(sum('current_prediction'))} color="#2BB3A3" />
            <Meter label="실측" n={sum('measurement')} pct={pct(sum('measurement'))} color="#7FD6C8" note={sum('synthetic') ? `+ 합성 ${sum('synthetic')}` : undefined} />
          </> : <p className="hd-dim">API 재시작 후 표시 (coverage-summary)</p>}
          {worst.length > 0 && <p className="hd-em">예측↔실측 최대 |Δ| {Math.max(...worst.map(Math.abs)).toFixed(1)}%</p>}
        </a>
        <div className="hd-block">
          <h3>Architecture 검토</h3>
          <a className="hd-row" href="#/predictions"><span>등록 예측</span><b>{board.data ? board.data.rows.length : '—'}</b></a>
          <a className="hd-row" href={run ? `#/explore?run=${encodeURIComponent(run.id)}` : '#/explore'}><span>최근 탐색</span>
            <b className="txt" title={run?.title}>{run ? `${run.summary.spec_ok}/${run.summary.variants} 만족 · ${run.created_at?.slice(5, 10) ?? ''}` : '없음'}</b></a>
          <a className="hd-row" href={report ? `#/reports?report=${encodeURIComponent(report.id)}` : '#/reports'}><span>보고서</span>
            <b className="txt">{reports.data ? `${reports.data.length}건 · 게시 ${published}` : '—'}{report ? ` · 최근 ${report.status}` : ''}</b></a>
        </div>
        <a className="hd-block" href="#/library">
          <h3>Library</h3>
          <div className="hd-row"><span>DVFS table</span><b>{dvfs.data ? dvfs.data.total : '—'}</b></div>
          {sampleDvfs > 0 && <p className="hd-em">SAMPLE/SYNTHETIC {sampleDvfs} — 사내 table 교체 필요</p>}
          {dvfs.data && dvfs.data.total === 0 && <p className="hd-em">DVFS 미연결 — level·전압 산출 불가</p>}
          <div className="hd-row"><span>IP catalog</span><b>{ips.data ? ips.data.total : '—'}</b></div>
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
