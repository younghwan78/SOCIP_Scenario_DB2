// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { PredictionCollaboration } from './PredictionCollaboration'
import { collaborationApi, type PredictionNotes, type PredictionComment } from '../lib/predictionCollaboration'
import { ApiError } from '../lib/api'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
afterEach(() => vi.restoreAllMocks())
const notes = (id: string, revision = 0, title = ''): PredictionNotes => ({ prediction_id: id, revision, title, purpose: '', description: '', assumptions: '', conclusion: '', tags: [], created_by: 'writer', updated_by: 'writer', created_at: null, updated_at: null })
const edit = (input: HTMLInputElement | HTMLTextAreaElement, value: string) => { Object.getOwnPropertyDescriptor(input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })) }

it('keeps the local notes draft through a conflict and saves only after latest revision is reviewed', async () => {
  const reads = vi.spyOn(collaborationApi, 'notes').mockResolvedValueOnce(notes('p1', 1, 'initial')).mockResolvedValue(notes('p1', 2, 'other writer'))
  vi.spyOn(collaborationApi, 'comments').mockResolvedValue({ prediction_id: 'p1', items: [], total: 0, limit: 25, offset: 0 })
  const save = vi.spyOn(collaborationApi, 'saveNotes').mockRejectedValueOnce(new ApiError('conflict', 409)).mockResolvedValue(notes('p1', 3, 'my draft'))
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<PredictionCollaboration predictionId="p1" />))
    act(() => edit(host.querySelector<HTMLInputElement>('[aria-label="제목"]')!, 'my draft'))
    await act(async () => [...host.querySelectorAll('button')].find((button) => button.textContent === '설명 저장')!.click())
    expect(reads).toHaveBeenCalledTimes(2)
    expect(host.textContent).toContain('other writer')
    expect(host.querySelector<HTMLInputElement>('[aria-label="제목"]')!.value).toBe('my draft')
    expect([...host.querySelectorAll('button')].find((button) => button.textContent === '설명 저장')!.disabled).toBe(true)
    act(() => [...host.querySelectorAll('button')].find((button) => button.textContent === '최신 버전 기준으로 내 초안 유지')!.click())
    await act(async () => [...host.querySelectorAll('button')].find((button) => button.textContent === '설명 저장')!.click())
    expect(save.mock.calls[1]).toEqual(['p1', expect.objectContaining({ title: 'my draft' }), 2])
  } finally { act(() => root.unmount()) }
})
it('isolates notes, reply and comment drafts and ignores late writes after switching prediction', async () => {
  vi.spyOn(collaborationApi, 'notes').mockImplementation(async (id) => notes(id, 1, id))
  vi.spyOn(collaborationApi, 'comments').mockImplementation(async (id) => ({ prediction_id: id, items: [{ id: `${id}-comment`, prediction_id: id, body: 'review', parent_id: null, created_by: 'analyst', created_at: null }], total: 1, limit: 25, offset: 0 }))
  let finish!: (comment: PredictionComment) => void
  const post = vi.spyOn(collaborationApi, 'comment').mockImplementation(() => new Promise((resolve) => { finish = resolve }))
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<PredictionCollaboration predictionId="old" />))
    act(() => { [...host.querySelectorAll('button')].find((button) => button.textContent === '답글')!.click(); edit(host.querySelector<HTMLTextAreaElement>('[aria-label="검토 의견"]')!, 'old response') })
    await act(async () => [...host.querySelectorAll('button')].find((button) => button.textContent === '답글 등록')!.click())
    expect(post.mock.calls[0]).toEqual(['old', 'old response', 'old-comment'])
    await act(async () => root.render(<PredictionCollaboration predictionId="new" />))
    await act(async () => finish({ id: 'late', prediction_id: 'old', parent_id: 'old-comment', body: 'old response', created_by: 'analyst', created_at: null }))
    expect(host.querySelector<HTMLTextAreaElement>('[aria-label="검토 의견"]')!.value).toBe('')
    expect(host.querySelector<HTMLInputElement>('[aria-label="제목"]')!.value).toBe('new')
    expect(host.textContent).not.toContain('old-comment')
    expect(host.textContent).not.toContain('댓글을 등록했습니다')
  } finally { act(() => root.unmount()) }
})
it('protects every editable draft while notes are saving and displays an empty comment count', async () => {
  vi.spyOn(collaborationApi, 'notes').mockResolvedValue(notes('p1', 1, 'draft'))
  vi.spyOn(collaborationApi, 'comments').mockResolvedValue({ prediction_id: 'p1', items: [], total: 0, limit: 25, offset: 0 })
  let finish!: (value: PredictionNotes) => void
  vi.spyOn(collaborationApi, 'saveNotes').mockImplementation(() => new Promise((resolve) => { finish = resolve }))
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<PredictionCollaboration predictionId="p1" />))
    expect(host.textContent).toContain('0건')
    expect(host.textContent).not.toContain('1–0')
    await act(async () => [...host.querySelectorAll('button')].find((button) => button.textContent === '설명 저장')!.click())
    const inputs = [...host.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('input, textarea')]
    expect(inputs.length).toBe(7)
    expect(inputs.every((input) => input.disabled)).toBe(true)
    await act(async () => finish(notes('p1', 2, 'draft')))
    expect(inputs.every((input) => !input.disabled)).toBe(true)
    expect(host.querySelector<HTMLInputElement>('[aria-label="제목"]')!.value).toBe('draft')
  } finally { act(() => root.unmount()) }
})
