/** S-10: why an "이전 engine" result differs — the revisions between its engine and today's, and what each moves. */
export interface EngineChange { rev: number; change: string; moves: string }

export function EngineChanges({ changes }: { changes?: EngineChange[] }) {
  if (!changes?.length) return null
  return <details className="engine-changes">
    <summary>그 사이 engine 변경 {changes.length}건</summary>
    <ul>{changes.map((c) => <li key={c.rev}><b className="mono">rev {c.rev}</b> {c.change} <span className="faint">— 움직이는 값: {c.moves}</span></li>)}</ul>
  </details>
}
