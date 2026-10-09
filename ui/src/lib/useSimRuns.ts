// One operation per result key; cancelled or replaced operations cannot update a newer preview.
import { useCallback, useEffect, useRef, useState } from 'react'
import { saveResult, type SaveState, type SimState } from './simRun'

type Done = Extract<SimState, { status: 'done' }>
export function useSimRuns() {
  const [sims, setSims] = useState<Record<string, SimState>>({})
  const entries = useRef<Record<string, SimState>>({})
  const operations = useRef(new Map<string, symbol>())
  const update = useCallback((key: string, state?: SimState) => {
    const next = { ...entries.current }
    if (state) next[key] = state
    else delete next[key]
    entries.current = next
    setSims(next)
  }, [])
  const cancel = useCallback((key: string) => { operations.current.delete(key); update(key) }, [update])
  useEffect(() => () => { operations.current.clear() }, [])

  const run = async (key: string, task: () => Promise<Done>): Promise<Done | undefined> => {
    if (operations.current.has(key)) return
    const token = Symbol()
    operations.current.set(key, token)
    update(key, { status: 'running' })
    try {
      const done = await task()
      if (operations.current.get(key) !== token) return
      update(key, done)
      return done
    } catch (e) {
      if (operations.current.get(key) === token) update(key, { status: 'error', error: e instanceof Error ? e.message : String(e) })
    } finally {
      if (operations.current.get(key) === token) operations.current.delete(key)
    }
  }
  const save = async (key: string): Promise<Extract<SaveState, { status: 'saved' }> | undefined> => {
    const st = entries.current[key]
    if (operations.current.has(key) || st?.status !== 'done' || st.res.persisted || st.save?.status === 'saved') return
    const token = Symbol()
    operations.current.set(key, token)
    update(key, { ...st, save: { status: 'saving' } })
    try {
      const saved = await saveResult(st.req)
      if (operations.current.get(key) !== token) return
      update(key, { ...st, save: saved })
      return saved
    } catch (e) {
      if (operations.current.get(key) === token) update(key, { ...st, save: { status: 'error', error: e instanceof Error ? e.message : String(e) } })
    } finally {
      if (operations.current.get(key) === token) operations.current.delete(key)
    }
  }
  return { sims, run, save, cancel }
}
