import { authVersion } from './auth'
import { postAdmitted } from './timingBudget'

interface Flight {
  promise: Promise<unknown>
  controller: AbortController
  subscribers: number
  shared: boolean
}
const flights = new Map<string, Flight>()
const aborted = (signal?: AbortSignal) => signal?.reason ?? new DOMException('Aborted', 'AbortError')

/** Share only concurrent, read-only calculations. Never reuse a settled result or a different identity.
 * Each subscriber owns its cancellation; a replacement effect in the same turn can adopt the request.
 * Aborting the HTTP request stops admission retries, not an already running server calculation.
 */
export function postCalculation<T>(path: string, request: unknown, signal?: AbortSignal): Promise<T> {
  if (signal?.aborted) return Promise.reject(aborted(signal))
  const key = `${authVersion()}|${path}|${JSON.stringify(request)}`
  let flight = flights.get(key)
  if (!flight || flight.controller.signal.aborted) {
    const controller = new AbortController()
    const promise = postAdmitted<T>(path, request, controller.signal)
    flight = { promise, controller, subscribers: 0, shared: false }
    flights.set(key, flight)
    const done = () => { if (flights.get(key) === flight) flights.delete(key) }
    promise.then(done, done)
  }
  const active = flight
  active.subscribers++
  if (active.subscribers > 1) active.shared = true
  return new Promise<T>((resolve, reject) => {
    let finished = false
    const finish = () => {
      if (finished) return false
      finished = true
      signal?.removeEventListener('abort', abort)
      active.subscribers--
      // React's cleanup/setup and same-input replacement run synchronously; keep their shared request.
      queueMicrotask(() => {
        if (!active.subscribers && flights.get(key) === active) {
          flights.delete(key)
          active.controller.abort()
        }
      })
      return true
    }
    const abort = () => { if (finish()) reject(aborted(signal)) }
    signal?.addEventListener('abort', abort, { once: true })
    active.promise.then((value) => {
      // Independent HTTP responses used to own independent objects. Keep that isolation when shared.
      if (finish()) resolve((active.shared ? structuredClone(value) : value) as T)
    }, (error: unknown) => { if (finish()) reject(error) })
  })
}
