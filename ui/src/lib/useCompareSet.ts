import { useEffect, useState } from 'react'
import type { Ctx } from '../App'
import { compareItems, formatItems, loadCompareSet, saveCompareSet } from './projects'

export function useCompareSet(ctx: Pick<Ctx, 'params' | 'scenario' | 'variant' | 'navigate'>) {
  const explicit = !!(ctx.params.items || ctx.params.variants)
  const [kept, setKept] = useState(() => explicit ? '' : loadCompareSet())
  const items = compareItems(!explicit && kept ? { ...ctx.params, items: kept } : ctx.params, ctx.scenario, ctx.variant)
  const encoded = formatItems(items)
  useEffect(() => {
    if (explicit) { saveCompareSet(encoded); setKept(encoded) }
    else if (kept) ctx.navigate(undefined, { items: kept, variants: undefined }, true)
  }, [ctx.params.items, ctx.params.variants, encoded, explicit, kept]) // eslint-disable-line react-hooks/exhaustive-deps
  const clear = () => {
    saveCompareSet(undefined)
    setKept('')
    ctx.navigate(undefined, { items: undefined, variants: undefined })
  }
  return { items, clear }
}
