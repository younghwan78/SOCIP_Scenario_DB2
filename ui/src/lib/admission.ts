// Simulation admission (server: N concurrent simulations per worker, non-blocking 429 + Retry-After).
// Every simulation-backed request waits and retries here instead of failing, and a small global store tells the
// UI that a request is queued behind other users' runs.
import { useSyncExternalStore } from 'react'

export interface AdmissionWait { waiting: number; since: number | null; attempts: number }
let state: AdmissionWait = { waiting: 0, since: null, attempts: 0 }
const listeners = new Set<() => void>()
const emit = (next: AdmissionWait) => { state = next; listeners.forEach((l) => l()) }
export const admissionState = () => state
export function useAdmissionWait(): AdmissionWait {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l) }, admissionState, admissionState)
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
/** Backoff for retry i: Retry-After (s) scaled up to 5 s, with jitter so queued clients do not retry in lockstep. */
export function backoffMs(i: number, retryAfter: number | null, rand = Math.random()): number {
  const base = retryAfter && Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : 1000
  return Math.min(5000, base * (0.5 + 0.25 * i)) + rand * 300
}
/** Total wait before giving up (the user can still re-run): long enough for a couple of other users' runs. */
export const ADMISSION_BUDGET_MS = 120_000

/** fetch with wait-and-retry on 429 (simulation slots busy). Non-429 responses are returned as is. */
export async function fetchAdmitted(url: string, init: RequestInit, budgetMs = ADMISSION_BUDGET_MS): Promise<Response> {
  const start = Date.now()
  let queued = false
  try {
    for (let i = 0; ; i++) {
      const res = await fetch(url, init)
      if (res.status !== 429 || Date.now() - start >= budgetMs) return res
      if (!queued) { queued = true; emit({ waiting: state.waiting + 1, since: state.since ?? Date.now(), attempts: state.attempts }) }
      emit({ ...state, attempts: state.attempts + 1 })
      await sleep(backoffMs(i, Number(res.headers?.get?.('Retry-After') ?? 1)))
    }
  } finally {
    if (queued) { const w = Math.max(0, state.waiting - 1); emit({ waiting: w, since: w ? state.since : null, attempts: w ? state.attempts : 0 }) }
  }
}
