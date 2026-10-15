import { useEffect, useState } from 'react'
import type { Ctx } from '../App'

export type Lens = 'sequence' | 'dma' | 'ip'
export type Mode = 'split' | 'graph' | 'timing'
const legacyLens = (l?: string): Lens => l === 'topology' ? 'sequence' : l === 'transform' ? 'ip' : l === 'dma' || l === 'ip' || l === 'sequence' ? l : 'sequence'

export function usePipelineNavigation(ctx: Pick<Ctx, 'scenario' | 'variant' | 'params' | 'navigate'>, mode: Mode, setMode: (mode: Mode) => void) {
  const lens = legacyLens(ctx.params.lens)
  const scope = JSON.stringify([ctx.scenario, ctx.variant])
  const [drill, setDrill] = useState<{ scope: string; lens: Lens; mode: Mode } | null>(null)
  const origin = drill?.scope === scope ? drill : null
  useEffect(() => {
    if (drill && drill.scope !== scope) setDrill(null)
    if (!origin) return
    if (lens === origin.lens) setMode(origin.mode)
    else if (lens === 'ip' && origin.mode === 'timing') setMode('split')
  }, [lens, drill, scope, setMode]) // eslint-disable-line react-hooks/exhaustive-deps
  const setLens = (next: Lens) => { setDrill(null); ctx.navigate(undefined, { lens: next }, true) }
  const openIpInternal = () => {
    if (lens === 'ip') return
    setDrill({ scope, lens, mode })
    if (mode === 'timing') setMode('split')
    ctx.navigate(undefined, { lens: 'ip' })
  }
  return { lens, setLens, openIpInternal, origin }
}
