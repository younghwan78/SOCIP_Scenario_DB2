import { getJson, postJson, requestJson } from './api'

export interface PredictionNotes {
  prediction_id: string; title: string; purpose: string; description: string; assumptions: string; conclusion: string; tags: string[]
  revision: number; created_by: string | null; updated_by: string | null; created_at: string | null; updated_at: string | null
}
export type NotesDraft = Pick<PredictionNotes, 'title' | 'purpose' | 'description' | 'assumptions' | 'conclusion' | 'tags'>
export interface PredictionComment { id: string; prediction_id: string; parent_id: string | null; body: string; created_by: string | null; created_at: string | null }
export interface CommentPage { prediction_id: string; items: PredictionComment[]; total: number; limit: number; offset: number }
const path = (id: string) => `/arch/predictions/${encodeURIComponent(id)}`
export const collaborationApi = {
  notes: (id: string) => getJson<PredictionNotes>(`${path(id)}/notes`, {}, false),
  saveNotes: (id: string, draft: NotesDraft, revision: number) => requestJson<PredictionNotes>('PUT', `${path(id)}/notes`, { ...draft, expected_revision: revision }),
  comments: (id: string, offset = 0) => getJson<CommentPage>(`${path(id)}/comments`, { offset, limit: 25 }, false),
  comment: (id: string, body: string, parentId?: string | null) => postJson<PredictionComment>(`${path(id)}/comments`, { body, parent_id: parentId ?? null }),
}
