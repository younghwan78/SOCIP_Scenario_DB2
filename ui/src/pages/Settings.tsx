import { useState } from 'react'
import type { Ctx } from '../App'
import { listExperimentContexts } from '../lib/experimentContext'
import { API_BASE, api } from '../lib/api'
import { useAsync } from '../lib/route'
import { Card } from '../components/TimingCharts'
import { setApiCredential, useCredentialKeyId } from '../lib/auth'

const STREAMLIT: string = (import.meta.env.VITE_STREAMLIT_BASE as string | undefined) ?? 'http://localhost:18502'
/** Streamlit pages kept until their React replacement ships (then retired). */
export const LEGACY_TOOLS: { page: string; label: string; react: string | null; note: string }[] = [
  { page: 'Evidence_Dashboard', label: 'Evidence Dashboard', react: '#/calibration', note: '예측 ↔ 실측으로 대체' },
  { page: 'Sensor_Catalog', label: 'Sensor Catalog', react: '#/library?tab=sensor', note: 'Library › Sensor로 대체' },
  { page: 'Camera_Profiling', label: 'Camera Profiling', react: null, note: '열람은 예측 ↔ 실측, 업로드는 2차 DB Import' },
  { page: 'Driver_Models', label: 'Driver Models', react: null, note: 'Library 확장 예정' },
  { page: 'Architecture_Query', label: 'Architecture Query', react: '#/whatif', note: '해상도 · FPS · IP clock What-if 지원' },
  { page: 'Exploration_Workbench', label: 'Exploration Workbench', react: '#/explore', note: 'recipe/sweep compile은 2차 Import' },
  { page: 'Import_Workbench', label: 'Import Workbench', react: null, note: '2차 DB Import' },
  { page: 'DB_Explorer', label: 'DB Explorer', react: '#/explorer', note: 'React로 대체 완료' },
  { page: 'Pipeline_Viewer', label: 'Pipeline Viewer', react: '#/pipeline', note: 'React로 대체 완료' },
  { page: 'Variant_Compare', label: 'Variant Compare', react: '#/compare', note: 'React로 대체 완료' },
]

export function SettingsPage({ ctx }: { ctx?: Ctx }) {
  const activeKey = useCredentialKeyId()
  const [keyId, setKeyId] = useState(activeKey)
  const [secret, setSecret] = useState('')
  const health = useAsync(() => api.health().then(() => 'ok').catch((e: unknown) => (e instanceof Error ? e.message : String(e))), [])
  const [cleared, setCleared] = useState<number | null>(null)
  const scopedLink = (href: string) => {
    if (!ctx) return href
    const [page, query] = href.split('?'), params = new URLSearchParams(query)
    params.set('project', ctx.project); params.set('scenario', ctx.scenario); params.set('variant', ctx.variant)
    return `${page}?${params}`
  }
  const clearPrefs = () => {
    let n = 0
    try { Object.keys(localStorage).filter((k) => k.startsWith('sdb.')).forEach((k) => { localStorage.removeItem(k); n++ }) } catch { /* storage blocked */ }
    setCleared(n)
  }
  return (
    <div className="page tb-page">
      <div className="tb-grid">
        <Card id="set-scope" title="연결된 작업 범위" note="페이지 이동 시 유지되는 기준" defaultWide>
          <div className="workflow-note"><b>{ctx?.project || '과제 미선택'}</b><span>{ctx?.scenario || 'Scenario 미선택'} / {ctx?.variant || 'Variant 미선택'}</span>
            <span>브라우저 실험 초안 {listExperimentContexts().filter((item) => !ctx || item.scope.project_ref === ctx.project).length}개 범위 · API 키별로 분리 · 이 탭의 sessionStorage에만 보관</span></div>
          <p className="faint">서버에 저장한 실험·검토 이력과 브라우저 초안은 별도입니다. API 연결 키를 변경하면 해당 키의 초안만 표시합니다.</p>
        </Card>
        <Card id="set-legacy" title="기존 도구 (Streamlit)" note="React 대체 전까지 유지 · 대체되면 은퇴" defaultWide>
          <table className="tb-mini-table" style={{ width: '100%' }}>
            <thead><tr><th>Streamlit page</th><th>React</th><th>상태</th><th /></tr></thead>
            <tbody>{LEGACY_TOOLS.map((t) => (
              <tr key={t.page}><td>{t.label}</td>
                <td>{t.react ? <a href={scopedLink(t.react)}>{t.react}</a> : <span className="faint">—</span>}</td>
                <td className="faint">{t.note}</td>
                <td><a className="btn tb-mini" href={`${STREAMLIT}/${t.page}`} target="_blank" rel="noreferrer">Streamlit 열기</a></td></tr>))}</tbody>
          </table>
          <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>Streamlit 주소: <span className="mono">{STREAMLIT}</span> (빌드 시 <span className="mono">VITE_STREAMLIT_BASE</span>로 변경)</div>
        </Card>
        <Card id="set-api" title="API 연결">
          <table className="tb-mini-table" style={{ width: '100%' }}><tbody>
            <tr><td>API base</td><td className="mono">{API_BASE}</td></tr>
            <tr><td>상태</td><td>{health.loading ? '확인 중…' : health.data === 'ok' ? <span className="badge v-ok">연결됨</span> : <span className="badge v-fail">{health.data}</span>}</td></tr>
            <tr><td>인증</td><td>{activeKey ? `연결 키: ${activeKey}` : 'API 키 없음'}</td></tr>
          </tbody></table>
          <p className="faint">등록·설명·댓글·개인 실험의 작성자는 서버가 API 키로 확인합니다. 키는 현재 창의 메모리에만 보관되며 새로고침하면 지워집니다.</p>
          <form className="collab-form" onSubmit={(e) => { e.preventDefault(); setApiCredential({ keyId, secret }); setSecret('') }}>
            <label>Key ID<input className="input" aria-label="API Key ID" autoComplete="off" value={keyId} onChange={(e) => setKeyId(e.target.value)} /></label>
            <label>API Key<input className="input" type="password" aria-label="API Key" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} /></label>
            <div><button className="btn primary" disabled={!keyId.trim() || !secret}>현재 창에 연결</button> <button className="btn" type="button" onClick={() => { setApiCredential(null); setSecret(''); setKeyId('') }}>연결 해제</button></div>
          </form>
        </Card>
        <Card id="set-prefs" title="화면 설정">
          <p className="faint" style={{ fontSize: 13, marginTop: 0 }}>카드 폭, 표 정렬·열 폭, sidebar 상태는 이 브라우저에만 저장됩니다.</p>
          <button className="btn" onClick={clearPrefs}>화면 설정 초기화</button>
          {cleared !== null && <span className="faint" style={{ fontSize: 12, marginLeft: 8 }}>{cleared}개 항목 초기화 · 새로고침하면 적용</span>}
        </Card>
      </div>
    </div>
  )
}
