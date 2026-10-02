// U1 provenance badge + U2 model status bar.
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { PROV_LABEL, provText, provenanceApi, statusItems, type Prov } from '../lib/provenance'

/** Small source badge; hover = engine · scope · model rev · DVFS · id. */
export function ProvBadge({ prov, compact = false }: { prov: Prov; compact?: boolean }) {
  return (
    <span className={`prov prov-${prov.kind}`} title={provText(prov)} aria-label={provText(prov).replace(/\n/g, ', ')}>
      {PROV_LABEL[prov.kind]}{!compact && prov.engine ? <span className="prov-eng"> · {prov.engine}</span> : null}
    </span>
  )
}

/** Value with its source; the same component on every page so numbers can be traced. */
export function ValueChip({ value, unit, prov }: { value: string; unit?: string; prov: Prov }) {
  return <span className="value-chip"><span className="mono">{value}</span>{unit && <span className="faint"> {unit}</span>} <ProvBadge prov={prov} compact /></span>
}

/** Model status for the selected 과제: DVFS sample, real/synthetic measurements, stale predictions, engine. */
export function ModelStatusBar({ ctx }: { ctx: Ctx }) {
  const q = useAsync(() => provenanceApi.modelStatus(ctx.project || undefined).catch(() => null), [ctx.project])
  if (!q.data) return null
  const items = statusItems(q.data, ctx.project)
  return (
    <div className="model-status" role="status" aria-label="모델 상태">
      <span className="ms-title">모델 상태</span>
      {items.map((it) => {
        const body = <><i className={`ms-dot ${it.level}`} />{it.text}</>
        return it.href
          ? <a key={it.key} className={`ms-item ${it.level}`} href={it.href} title={it.title}>{body}</a>
          : <span key={it.key} className={`ms-item ${it.level}`} title={it.title}>{body}</span>
      })}
    </div>
  )
}
