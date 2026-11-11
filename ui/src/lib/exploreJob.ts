import { useSyncExternalStore } from 'react'
import { archApi } from './archExplore'
import { notify } from './status'

/** Server exploration job (POST /arch/exploration/jobs). */
export type ExploreJob = {
  id: string
  status: 'queued' | 'running' | 'completed' | 'cancelled' | 'failed' | 'interrupted'
  completed_variants: number
  total_variants: number
  current_variant: string | null
  failed_variants: number
  run_id: string | null
  summary: { variants?: number; errors?: number; spec_ok?: number } | null
  cancel_requested: boolean
  error: string | null
  resumable: boolean
}

export type TrackedJob = { job: ExploreJob; title: string; project: string | null }

const KEY = 'sdb.explore.job'
const POLL_MS = 1000
const ACTIVE = new Set(['queued', 'running'])
let tracked: TrackedJob | null = null
let timer: ReturnType<typeof setTimeout> | null = null
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((listener) => listener())
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }

export const isActive = (job: ExploreJob | null | undefined) => !!job && ACTIVE.has(job.status)

function save(value: TrackedJob | null) {
  try {
    if (value && isActive(value.job)) window.localStorage.setItem(KEY, JSON.stringify({ id: value.job.id, title: value.title, project: value.project }))
    else window.localStorage.removeItem(KEY)
  } catch { /* storage unavailable: tracking still works for this page load */ }
}

function finished(value: TrackedJob) {
  const { job, title } = value
  if (job.status === 'completed') {
    const s = job.summary ?? {}
    notify({ kind: 'ok', text: `탐색 완료: ${title} · variant ${s.variants ?? 0}개${s.errors ? ` · 실패 ${s.errors}` : ''}` })
  } else if (job.status === 'failed') notify({ kind: 'error', text: `탐색 실패: ${title} · ${job.error ?? ''}` })
  else notify({ kind: 'info', text: `탐색 ${job.status === 'cancelled' ? '취소' : '중단'}: ${title} (${job.completed_variants}/${job.total_variants} variant)` })
}

function set(value: TrackedJob | null) {
  const wasActive = isActive(tracked?.job)
  tracked = value
  save(value)
  emit()
  if (value && wasActive && !isActive(value.job)) finished(value)
}

function schedule() {
  if (timer) clearTimeout(timer)
  timer = null
  if (!tracked || !isActive(tracked.job)) return
  timer = setTimeout(poll, POLL_MS)
}

async function poll() {
  const current = tracked
  if (!current) return
  try {
    const job = await archApi.job(current.job.id)
    if (tracked?.job.id !== current.job.id) return
    set({ ...current, job })
  } catch (e) {
    // a lost job (server restart, other account) stops tracking with one visible message
    if (tracked?.job.id === current.job.id) {
      tracked = null
      save(null)
      emit()
      notify({ kind: 'error', text: `탐색 진행 조회 실패: ${e instanceof Error ? e.message : String(e)}` })
    }
    return
  }
  schedule()
}

/** Start following a job (after submit / resume); survives page changes and reloads. */
export function trackExploreJob(job: ExploreJob, title: string, project: string | null) {
  tracked = null
  set({ job, title, project })
  schedule()
}

/** Called once by the app: picks up a job that was running when the page was left or reloaded. */
export function restoreExploreJob() {
  if (tracked) return
  let raw: string | null = null
  try { raw = window.localStorage.getItem(KEY) } catch { return }
  if (!raw) return
  try {
    const { id, title, project } = JSON.parse(raw) as { id: string; title: string; project: string | null }
    tracked = { job: { id, status: 'queued', completed_variants: 0, total_variants: 0, current_variant: null, failed_variants: 0,
      run_id: null, summary: null, cancel_requested: false, error: null, resumable: false }, title, project }
    emit()
    void poll()
  } catch { save(null) }
}

export async function cancelExploreJob() {
  if (!tracked) return
  const current = tracked
  const job = await archApi.cancelJob(current.job.id)
  if (tracked?.job.id === current.job.id) { set({ ...current, job }); schedule() }
}

export async function resumeExploreJob() {
  if (!tracked) return
  const current = tracked
  const job = await archApi.resumeJob(current.job.id)
  if (tracked?.job.id === current.job.id) { tracked = null; set({ ...current, job }); schedule() }
}

/** Forget a finished job (the panel's close button). */
export function clearExploreJob() {
  if (timer) clearTimeout(timer)
  timer = null
  tracked = null
  save(null)
  emit()
}

export const useExploreJob = () => useSyncExternalStore(subscribe, () => tracked, () => null)

/** Test hook: reset module state. */
export function _resetExploreJob() { clearExploreJob() }
