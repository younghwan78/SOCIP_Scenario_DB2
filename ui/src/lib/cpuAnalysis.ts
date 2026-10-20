import type { CpuSweep, CpuSweepRequest } from './cpu'
import type { GrowthSweep } from './growthSweep'
import type { CpuRebalance, CpuRebalanceRequest } from './rebalance'

export type GrowthRequest = CpuRebalanceRequest & { growths: number[] }

export interface CpuRun {
  n: number; profile: string; target: string; cmp: string | null; context: string
  growth: number; bwScale: number; pgEff: number
  ref_mw: number; best_mw: number | null; cmp_ref_mw: number | null; cmp_best_mw: number | null; winner: string | null
  /** CPU → DRAM MB/s of the run (BW-only effect of the BW scale). */
  bw_mbs?: number | null
  /** Kept across reloads together with the calculation's request context. */
  at?: string
}

/** Owned HTTP calls in production; a controlled in-memory adapter in workflow tests. */
export interface CpuAnalysisAdapter {
  sweep(request: CpuSweepRequest): Promise<CpuSweep>
  rebalance(request: CpuRebalanceRequest): Promise<CpuRebalance>
  growth(request: GrowthRequest): Promise<GrowthSweep>
}

export type CpuAnalysisPlan =
  | { mode: 'sweep'; request: CpuSweepRequest }
  | { mode: 'rebalance' | 'growth'; request: CpuRebalanceRequest; growths: number[]; comparison?: string }

export interface CpuAnalysisState {
  result: CpuSweep | null
  rebalance: CpuRebalance | null
  comparison: CpuRebalance | null
  growth: { result: GrowthSweep; request: GrowthRequest } | null
  comparisonGrowth: GrowthSweep | null
  error: string | null
  comparisonError: string | null
  growthError: string | null
  comparisonGrowthError: string | null
  busy: boolean
  growthBusy: boolean
  /** Only the latest completed workflow may supply a review snapshot. */
  snapshotRequest: GrowthRequest | null
  runs: CpuRun[]
}

const empty = (runs: CpuRun[]): CpuAnalysisState => ({
  result: null, rebalance: null, comparison: null, growth: null, comparisonGrowth: null,
  error: null, comparisonError: null, growthError: null, comparisonGrowthError: null,
  busy: false, growthBusy: false, snapshotRequest: null, runs,
})
const message = (error: unknown) => error instanceof Error ? error.message : String(error)

/** A comparison keeps the measured base and excludes; target-specific placement cannot carry over. */
function onComparison(request: CpuRebalanceRequest, comparison: string): CpuRebalanceRequest {
  return {
    ...request, power_params_ref: comparison,
    base_power_params_ref: request.base_power_params_ref || request.power_params_ref,
    pool: [], locks: Object.fromEntries(Object.entries(request.locks).filter(([, lock]) => lock === 'exclude')),
  }
}

/**
 * Owns one CPU analysis at a time, including its downstream comparison and growth calculations.
 * Replacing/cancelling an operation prevents every remaining stage from publishing or starting.
 * Admission/retries remain the adapter's responsibility; stages are deliberately sequential.
 */
export function createCpuAnalysis(adapter: CpuAnalysisAdapter, initialRuns: CpuRun[] = []) {
  let state = empty(structuredClone(initialRuns))
  let generation = 0
  let growthGeneration = -1
  const listeners = new Set<() => void>()
  const publish = (patch: Partial<CpuAnalysisState>) => {
    const next = { ...state, ...patch }
    next.snapshotRequest = !next.busy && !next.growthBusy && growthGeneration === generation
      ? next.growth?.request ?? null : null
    state = next
    listeners.forEach((listener) => listener())
  }
  const cancel = () => {
    ++generation
    publish({ busy: false, growthBusy: false })
  }
  const runGrowth = async (request: GrowthRequest, comparison: string | undefined, id: number) => {
    publish({ growthBusy: true, growthError: null, comparisonGrowth: null, comparisonGrowthError: null })
    try {
      const result = await adapter.growth(request)
      if (id !== generation) return
      growthGeneration = id
      publish({ growth: { result, request } })
      if (comparison && comparison !== request.power_params_ref) {
        try {
          const result = await adapter.growth({ ...onComparison(request, comparison), growths: request.growths })
          if (id === generation) publish({ comparisonGrowth: result })
        } catch (error) {
          if (id === generation) publish({ comparisonGrowthError: message(error) })
        }
      }
    } catch (error) {
      if (id === generation) publish({ growth: null, growthError: message(error) })
    } finally {
      if (id === generation) publish({ growthBusy: false })
    }
  }
  const execute = async (input: CpuAnalysisPlan) => {
    // Freeze the calculation's inputs before the first await, including nested task edits and growths.
    const plan = structuredClone(input)
    const id = ++generation
    publish({
      busy: plan.mode !== 'growth', growthBusy: plan.mode === 'growth',
      error: null, growthError: null, comparisonGrowth: null, comparisonGrowthError: null,
      ...(plan.mode !== 'growth' ? { comparison: null, comparisonError: null } : {}),
    })
    try {
      if (plan.mode === 'sweep') {
        const result = await adapter.sweep(plan.request)
        if (id === generation) publish({ result })
        return
      }
      if (plan.mode === 'rebalance') {
        const result = await adapter.rebalance(plan.request)
        if (id !== generation) return
        publish({ rebalance: result })
        let comparison: CpuRebalance | null = null
        if (plan.comparison && plan.comparison !== plan.request.power_params_ref) {
          try {
            comparison = await adapter.rebalance(onComparison(plan.request, plan.comparison))
            if (id !== generation) return
            publish({ comparison })
          } catch (error) {
            if (id !== generation) return
            publish({ comparisonError: message(error) })
          }
        }
        const { default_growth: _growth, cpu_bw_scale: _bw, ...context } = plan.request
        const run: CpuRun = {
          context: JSON.stringify(context), at: new Date().toISOString(),
          n: (state.runs[state.runs.length - 1]?.n ?? 0) + 1,
          profile: plan.request.cpu_profile_ref, target: plan.request.power_params_ref,
          cmp: comparison ? plan.comparison ?? null : null,
          growth: plan.request.default_growth ?? 1, bwScale: plan.request.cpu_bw_scale ?? 1,
          pgEff: plan.request.power_gating_eff ?? 0.9,
          ref_mw: result.reference.total_mw, best_mw: result.best?.total_mw ?? null,
          cmp_ref_mw: comparison?.reference.total_mw ?? null, cmp_best_mw: comparison?.best?.total_mw ?? null,
          winner: result.strategies?.winner ?? null, bw_mbs: result.cpu_bw_mbs ?? null,
        }
        publish({ runs: [...state.runs.slice(-19), run] })
      }
      if (id === generation) await runGrowth({ ...plan.request, growths: plan.growths }, plan.comparison, id)
    } catch (error) {
      if (id === generation) publish({ error: message(error) })
    } finally {
      if (id === generation) publish({ busy: false })
    }
  }
  return {
    getSnapshot: () => state,
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } },
    execute,
    cancel,
    // Selection transitions clear the sweep; retries retain the last successful result.
    // Reference/mode/comparison changes keep rebalance and growth visible until replaced.
    reset: ({ keepRebalance = false }: { keepRebalance?: boolean } = {}) => {
      ++generation
      publish({
        ...empty(state.runs),
        ...(keepRebalance ? {
          rebalance: state.rebalance, comparison: state.comparison, comparisonError: state.comparisonError,
          growth: state.growth,
        } : {}),
      })
    },
    clearHistory: () => publish({ runs: [] }),
  }
}
