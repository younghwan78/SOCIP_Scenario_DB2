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
  /** Request of the last growth that completed for the current workflow; cleared when a new one starts. */
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
 *
 * Two tokens keep the pre-module page semantics exactly:
 * - `generation` (the page's former `requestId`): a sweep/rebalance workflow. A new workflow or
 *   `cancel` stops every remaining stage of the previous one from publishing or starting.
 * - `growthToken` (the former `sweepId`): one growth stage. A standalone growth run supersedes only
 *   the pending growth; an in-flight rebalance keeps running and later starts its own growth.
 * Admission/retries remain the adapter's responsibility; stages are deliberately sequential.
 */
export function createCpuAnalysis(adapter: CpuAnalysisAdapter, initialRuns: CpuRun[] = []) {
  let state = empty(structuredClone(initialRuns))
  let generation = 0
  let growthToken = 0
  const listeners = new Set<() => void>()
  const publish = (patch: Partial<CpuAnalysisState>) => {
    state = { ...state, ...patch }
    listeners.forEach((listener) => listener())
  }
  /** Stop publishing for the current workflow and growth; displayed state is left as is. */
  const cancel = () => { ++generation; ++growthToken }
  const runGrowth = async (request: GrowthRequest, comparison: string | undefined, id: number) => {
    const token = ++growthToken
    const live = () => token === growthToken && id === generation
    publish({ growthBusy: true, growthError: null, snapshotRequest: null, comparisonGrowth: null, comparisonGrowthError: null })
    try {
      const result = await adapter.growth(request)
      if (!live()) return
      publish({ growth: { result, request }, snapshotRequest: request })
      if (comparison && comparison !== request.power_params_ref) {
        try {
          const result = await adapter.growth({ ...onComparison(request, comparison), growths: request.growths })
          if (live()) publish({ comparisonGrowth: result })
        } catch (error) {
          if (live()) publish({ comparisonGrowthError: message(error) })
        }
      }
    } catch (error) {
      if (live()) publish({ growthError: message(error), growth: null })
    } finally {
      if (token === growthToken) publish({ growthBusy: false })
    }
  }
  const execute = async (input: CpuAnalysisPlan) => {
    // Freeze the calculation's inputs before the first await, including nested task edits and growths.
    const plan = structuredClone(input)
    if (plan.mode === 'growth') {
      // A standalone growth belongs to the current workflow and does not replace it.
      return runGrowth({ ...plan.request, growths: plan.growths }, plan.comparison, generation)
    }
    const id = ++generation
    if (plan.mode === 'rebalance') ++growthToken  // a rebalance owns the next growth stage
    publish({
      busy: true, error: null,
      ...(plan.mode === 'rebalance'
        ? { growthBusy: false, snapshotRequest: null, comparisonGrowth: null, comparisonGrowthError: null } : {}),
    })
    try {
      if (plan.mode === 'sweep') {
        const result = await adapter.sweep(plan.request)
        if (id === generation) publish({ result })
        return
      }
      const result = await adapter.rebalance(plan.request)
      if (id !== generation) return
      // The previous comparison stays visible until the new main result arrives.
      publish({ rebalance: result, comparison: null, comparisonError: null })
      let comparison: CpuRebalance | null = null
      if (plan.comparison && plan.comparison !== plan.request.power_params_ref) {
        try {
          const response = await adapter.rebalance(onComparison(plan.request, plan.comparison))
          if (id === generation) { publish({ comparison: response }); comparison = response }
        } catch (error) {
          if (id === generation) publish({ comparisonError: message(error) })
        }
      }
      if (id === generation) {
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
    /**
     * Selection/mode transition: clears the sweep and the growth stage. A changed input selection
     * (`keepRebalance: false`) also drops the rebalance and growth results; errors, the comparison
     * and the busy flag are left to the next run, as before.
     */
    reset: ({ keepRebalance = false }: { keepRebalance?: boolean } = {}) => {
      ++growthToken
      publish({
        result: null, growthBusy: false, growthError: null, snapshotRequest: null,
        comparisonGrowth: null, comparisonGrowthError: null,
        ...(keepRebalance ? {} : { rebalance: null, growth: null }),
      })
    },
    clearHistory: () => publish({ runs: [] }),
  }
}
