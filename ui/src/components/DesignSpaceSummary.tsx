import { axisSummary, type DesignSpace } from '../lib/designSpace'

/** What the run evaluated per lever, as text (no hover needed): explored levers as is, held levers muted. */
export function DesignSpaceSummary({ space }: { space: DesignSpace | null | undefined }) {
  if (!space?.axes?.length) return null
  const rows = space.axes.map((axis) => axisSummary(axis, space))
  return (
    <div className="ds-summary" aria-label="탐색 공간">
      <span className="muted">탐색 공간</span>
      {rows.map((r, i) => (
        <span key={`${space.axes[i].lever}-${i}`} className={`chip ${r.explored ? '' : 'ds-held'}`}><b>{r.label}</b> {r.text}</span>))}
    </div>
  )
}
