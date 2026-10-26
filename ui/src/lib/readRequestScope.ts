let signal: AbortSignal | undefined

/** A hook's synchronous read launches share its lifetime; async pagers capture this value. */
export const currentReadSignal = () => signal
export function withReadSignal<T>(next: AbortSignal, launch: () => T): T {
  const previous = signal
  signal = next
  try { return launch() } finally { signal = previous }
}
