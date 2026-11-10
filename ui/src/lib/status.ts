import { useSyncExternalStore } from 'react'

type Notice = { kind: 'ok' | 'error' | 'info'; text: string }
export type StatusNotice = Notice & { id: number }

const EMPTY: StatusNotice[] = []
let notices = EMPTY
let nextId = 0
const listeners = new Set<() => void>()
const timers = new Map<number, ReturnType<typeof setTimeout>>()
const emit = () => listeners.forEach((listener) => listener())
const snapshot = () => notices
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }

export function dismissStatus(id: number) {
  clearTimeout(timers.get(id))
  timers.delete(id)
  notices = notices.filter((notice) => notice.id !== id)
  emit()
}

export function notify(notice: Notice): number {
  const id = ++nextId
  notices = [...notices, { ...notice, id }]
  if (notice.kind !== 'error') timers.set(id, setTimeout(() => dismissStatus(id), 5000))
  emit()
  return id
}

export const useStatusNotices = () => useSyncExternalStore(subscribe, snapshot, () => EMPTY)
