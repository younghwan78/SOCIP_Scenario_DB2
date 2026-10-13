import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../lib/api'
import { useCredentialKeyId } from '../lib/auth'
import { useAsync } from '../lib/route'
import { collaborationApi, type NotesDraft, type PredictionNotes } from '../lib/predictionCollaboration'
import { Card } from './TimingCharts'

const fields = [{ key: 'title', label: '제목', max: 200 }, { key: 'purpose', label: '검토 목적', max: 2000 }, { key: 'description', label: '상세 설명 · 변경 이유', max: 10000 }, { key: 'assumptions', label: '가정 · 제약', max: 10000 }, { key: 'conclusion', label: '결론 · 추가 검증', max: 10000 }] as const
const draftOf = (notes: PredictionNotes): NotesDraft => ({ title: notes.title, purpose: notes.purpose, description: notes.description, assumptions: notes.assumptions, conclusion: notes.conclusion, tags: [...notes.tags] })
const date = (value: string | null) => value ? new Date(value).toLocaleString('ko-KR') : '—'
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error)

/** The keyed boundary resets all drafts when selecting a different prediction. */
export function PredictionCollaboration({ predictionId }: { predictionId: string }) {
  const actor = useCredentialKeyId()
  return <CollaborationBody key={JSON.stringify([predictionId, actor])} predictionId={predictionId} />
}
function CollaborationBody({ predictionId }: { predictionId: string }) {
  const [tick, setTick] = useState(0)
  const [offset, setOffset] = useState(0)
  const notesQ = useAsync(() => collaborationApi.notes(predictionId), [predictionId, tick])
  const commentsQ = useAsync(() => collaborationApi.comments(predictionId, offset), [predictionId, offset, tick])
  const [draft, setDraft] = useState<NotesDraft | null>(null)
  const [revision, setRevision] = useState<number | null>(null)
  const [conflict, setConflict] = useState(false)
  const [message, setMessage] = useState('')
  const [comment, setComment] = useState('')
  const [replyTo, setReplyTo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const live = useRef(true)
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  useEffect(() => { if (notesQ.data && draft === null) { setDraft(draftOf(notesQ.data)); setRevision(notesQ.data.revision) } }, [notesQ.data, draft])
  const save = async () => {
    if (!draft || revision === null || conflict || busyRef.current) return
    busyRef.current = true; setBusy(true); setMessage('')
    try {
      const result = await collaborationApi.saveNotes(predictionId, { ...draft, tags: draft.tags.filter(Boolean) }, revision)
      if (live.current) { setDraft(draftOf(result)); setRevision(result.revision); setMessage('설명을 저장했습니다.'); setTick((n) => n + 1) }
    } catch (error) { if (live.current) {
      if (error instanceof ApiError && error.status === 409) { setConflict(true); setTick((n) => n + 1); setMessage('다른 사용자가 설명을 수정했습니다. 최신 내용과 아래 초안을 비교한 후 최신 버전을 기준으로 저장하세요.') }
      else setMessage(errorText(error))
    } } finally { busyRef.current = false; if (live.current) setBusy(false) }
  }
  const addComment = async () => {
    if (!comment.trim() || busyRef.current) return
    const body = comment.trim(), parent = replyTo
    busyRef.current = true; setBusy(true); setMessage('')
    try { await collaborationApi.comment(predictionId, body, parent); if (live.current) { setComment(''); setReplyTo(null); setOffset(0); setTick((n) => n + 1); setMessage('댓글을 등록했습니다.') } }
    catch (error) { if (live.current) setMessage(errorText(error)) }
    finally { busyRef.current = false; if (live.current) setBusy(false) }
  }
  return <Card id="pr-collaboration" title="실험 기록 · 검토 의견" note={`예측 ${predictionId} · 계산 결과에 연결된 설명과 댓글`} defaultWide>
    {(notesQ.error || commentsQ.error) && <div className="err">{notesQ.error || commentsQ.error}</div>}
    {notesQ.data && <p className="faint collab-meta">작성 {notesQ.data.created_by ?? '미작성'} · {date(notesQ.data.created_at)} / 수정 {notesQ.data.updated_by ?? '—'} · {date(notesQ.data.updated_at)} · revision {notesQ.data.revision}</p>}
    {conflict && notesQ.data && <div className="collab-conflict">
      <b>최신 저장 내용</b>
      {fields.map(({ key, label }) => <p key={key}><b>{label}</b><br />{notesQ.data![key] || '—'}</p>)}
      <p>태그: {notesQ.data.tags.join(', ') || '—'}</p>
      <button className="btn" disabled={busy || notesQ.loading} onClick={() => { setRevision(notesQ.data!.revision); setConflict(false); setMessage('현재 초안을 최신 버전 위에 저장할 수 있습니다. 변경 내용을 확인하세요.') }}>최신 버전 기준으로 내 초안 유지</button>{' '}
      <button className="btn" disabled={busy || notesQ.loading} onClick={() => { setDraft(draftOf(notesQ.data!)); setRevision(notesQ.data!.revision); setConflict(false); setMessage('최신 내용을 불러왔습니다.') }}>최신 내용으로 초안 교체</button>
    </div>}
    {draft ? <div className="collab-form">
      {fields.map(({ key, label, max }) => <label key={key}>{label}{key === 'title' ? <input className="input" disabled={busy} value={draft[key]} maxLength={max} aria-label={label} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} /> : <textarea className="input" disabled={busy} rows={key === 'description' ? 4 : 2} value={draft[key]} maxLength={max} aria-label={label} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />}</label>)}
      <label>태그 (쉼표 구분)<input className="input" disabled={busy} aria-label="설명 태그" value={draft.tags.join(', ')} onChange={(e) => setDraft({ ...draft, tags: e.target.value.split(',').map((tag) => tag.trim()).slice(0, 20) })} /></label>
      <div><button className="btn primary" disabled={busy || conflict || revision === null || draft.tags.some((tag) => tag.length > 50)} onClick={save}>설명 저장</button></div>
    </div> : <div className="faint">설명 불러오는 중…</div>}
    <h4>댓글 · 답글 ({commentsQ.data?.total ?? 0})</h4>
    <div className="collab-comments">{commentsQ.data?.items.map((item) => <article key={item.id} className={item.parent_id ? 'collab-reply' : ''}>
      <div className="collab-meta faint">{item.created_by ?? '작성자 미상'} · {date(item.created_at)}{item.parent_id ? ` · 답글 대상 ${item.parent_id}` : ''}</div>
      <p>{item.body}</p><button className="btn tb-mini" disabled={busy} onClick={() => setReplyTo(item.id)}>답글</button>
    </article>)}</div>
    <div className="toolbar"><button className="btn tb-mini" disabled={offset === 0 || commentsQ.loading || busy} onClick={() => setOffset(Math.max(0, offset - 25))}>이전 댓글</button><span className="faint">{commentsQ.data?.items.length ? `${offset + 1}–${offset + commentsQ.data.items.length}` : '0건'}</span><button className="btn tb-mini" disabled={!commentsQ.data || offset + commentsQ.data.items.length >= commentsQ.data.total || commentsQ.loading || busy} onClick={() => setOffset(offset + 25)}>다음 댓글</button></div>
    {replyTo && <div className="faint">답글 대상: {replyTo} <button className="btn tb-mini" disabled={busy} onClick={() => setReplyTo(null)}>취소</button></div>}
    <label className="collab-form">검토 의견<textarea className="input" disabled={busy} rows={3} maxLength={5000} aria-label="검토 의견" value={comment} onChange={(e) => setComment(e.target.value)} /></label>
    <button className="btn primary" disabled={busy || !comment.trim()} onClick={addComment}>{replyTo ? '답글 등록' : '댓글 등록'}</button>
    {message && <p role="status">{message}</p>}
  </Card>
}
