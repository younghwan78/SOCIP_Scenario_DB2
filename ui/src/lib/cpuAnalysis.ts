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
  sweep(request: CpuSweepRequest, signal?: AbortSignal): Promise<CpuSweep>
  rebalance(request: CpuRebalanceRequest, signal?: AbortSignal): Promise<CpuRebalance>
  growth(request: GrowthRequest, signal?: AbortSignal): Promise<GrowthSweep>
}

/**
 * `key`: the page's fingerprint of the inputs behind this calculation. It is stored with the result it
 * produces (`keys`), so the page can tell a result computed from other inputs (stale) from a current one.
 * A rebalance runs its growth stage with `growthKey`.
 */
export type CpuAnalysisPlan =
  | { mode: 'sweep'; request: CpuSweepRequest; key?: string }
  | { mode: 'rebalance' | 'growth'; request: CpuRebalanceRequest; growths: number[]; comparison?: string; key?: string; growthKey?: string }

/** One server call of a workflow, in execution order. */
export type CpuStage = 'sweep' | 'rebalance' | 'comparison' | 'growth' | 'growth-comparison'
/** The workflow in flight: its planned stages, the one running now and when it started (ms epoch). */
export interface CpuProgress { mode: 'sweep' | 'rebalance' | 'growth'; stages: CpuStage[]; index: number; startedAt: number }
/**
 * How the last workflow ended; `ms` = wall time of all its stages. `partial` = the main result arrived but a later
 * stage (`failed`) did not; `error` = the first stage failed.
 */
export interface CpuDone { mode: 'sweep' | 'rebalance' | 'growth'; outcome: 'ok' | 'partial' | 'error' | 'cancelled'; at: number; ms: number; failed?: CpuStage[] }

export const STAGE_LABEL: Record<CpuStage, string> = {
  sweep: 'knob 자동 탐색', rebalance: 'MID 재분배', comparison: '과제 비교 재분배',
  growth: 'SW 증가 곡선', 'growth-comparison': '과제 비교 SW 증가 곡선',
}

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
  /** Workflow in flight (null when idle). */
  progress: CpuProgress | null
  /** Last finished workflow. */
  done: CpuDone | null
  /** Input fingerprint (plan `key`) of each displayed result; null = none or not given. */
  keys: { sweep: string | null; rebalance: string | null; growth: string | null }
}

const NO_KEYS = { sweep: null, rebalance: null, growth: null }
const empty = (runs: CpuRun[]): CpuAnalysisState => ({
  result: null, rebalance: null, comparison: null, growth: null, comparisonGrowth: null,
  error: null, comparisonError: null, growthError: null, comparisonGrowthError: null,
  busy: false, growthBusy: false, snapshotRequest: null, runs, progress: null, done: null, keys: NO_KEYS,
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
export function createCpuAnalysis(adapter: CpuAnalysisAdapter, initialRuns: CpuRun[] = [], now: () => number = Date.now) {
  let state = empty(structuredClone(initialRuns))
  let generation = 0
  let growthToken = 0
  let mainController: AbortController | undefined
  let growthController: AbortController | undefined
  /** Owner of `state.progress`: `m<generation>` for a sweep/rebalance workflow, `g<token>` for a standalone growth. */
  let progressOwner: string | null = null
  const listeners = new Set<() => void>()
  const publish = (patch: Partial<CpuAnalysisState>) => {
    state = { ...state, ...patch }
    listeners.forEach((listener) => listener())
  }
  const begin = (owner: string, mode: CpuProgress['mode'], stages: CpuStage[]) => {
    progressOwner = owner
    publish({ progress: { mode, stages, index: 0, startedAt: now() } })
  }
  const step = (owner: string, stage: CpuStage) => {
    const p = state.progress
    if (progressOwner !== owner || !p) return
    const index = p.stages.indexOf(stage, p.index)
    if (index > p.index) publish({ progress: { ...p, index } })
  }
  const finish = (owner: string, outcome: CpuDone['outcome'], failed: CpuStage[] = []) => {
    const p = state.progress
    if (progressOwner !== owner || !p) return
    progressOwner = null
    const at = now()
    const result = outcome === 'ok' && failed.length ? 'partial' : outcome
    publish({ progress: null, done: { mode: p.mode, outcome: result, at, ms: at - p.startedAt, ...(failed.length ? { failed } : {}) } })
  }
  /** Stop publishing for the current workflow and growth; displayed results are left as is. */
  const cancel = () => {
    ++generation; ++growthToken
    mainController?.abort()
    growthController?.abort()
    if (progressOwner !== null) { progressOwner = null; publish({ progress: null }) }
  }
  const withComparison = (comparison: string | undefined, target: string) => !!comparison && comparison !== target
  /** Resolves to the stages that failed (empty = all published). */
  const runGrowth = async (request: GrowthRequest, comparison: string | undefined, id: number, key: string | undefined,
                           owner?: string): Promise<CpuStage[]> => {
    const failed: CpuStage[] = []
    const token = ++growthToken
    growthController?.abort()
    const controller = growthController = new AbortController()
    const live = () => token === growthToken && id === generation
    const cmp = withComparison(comparison, request.power_params_ref)
    // a standalone growth reports its own progress unless a sweep/rebalance workflow is in flight
    const mine = owner ?? (progressOwner === null || progressOwner.startsWith('g') ? `g${token}` : undefined)
    if (owner) step(owner, 'growth')
    else if (mine) begin(mine, 'growth', cmp ? ['growth', 'growth-comparison'] : ['growth'])
    let outcome: CpuDone['outcome'] = 'ok'
    publish({ growthBusy: true, growthError: null, snapshotRequest: null, comparisonGrowth: null, comparisonGrowthError: null })
    try {
      const result = await adapter.growth(request, controller.signal)
      if (!live()) return failed
      publish({ growth: { result, request }, snapshotRequest: request, keys: { ...state.keys, growth: key ?? null } })
      if (cmp) {
        if (mine) step(mine, 'growth-comparison')
        try {
          const result = await adapter.growth({ ...onComparison(request, comparison!), growths: request.growths }, controller.signal)
          if (live()) publish({ comparisonGrowth: result })
        } catch (error) {
          failed.push('growth-comparison')
          if (live()) publish({ comparisonGrowthError: message(error) })
        }
      }
    } catch (error) {
      outcome = 'error'
      failed.push('growth')
      if (live()) publish({ growthError: message(error), growth: null, keys: { ...state.keys, growth: null } })
    } finally {
      if (token === growthToken) {
        publish({ growthBusy: false })
        if (!owner && mine) finish(mine, outcome, outcome === 'ok' ? failed : [])
      }
    }
    return failed
  }
  const execute = async (input: CpuAnalysisPlan) => {
    // Freeze the calculation's inputs before the first await, including nested task edits and growths.
    const plan = structuredClone(input)
    if (plan.mode === 'growth') {
      // A standalone growth belongs to the current workflow and does not replace it.
      return runGrowth({ ...plan.request, growths: plan.growths }, plan.comparison, generation, plan.key)
    }
    const id = ++generation
    const owner = `m${id}`
    mainController?.abort()
    growthController?.abort()
    const controller = mainController = new AbortController()
    if (plan.mode === 'rebalance') ++growthToken  // a rebalance owns the next growth stage
    const cmp = plan.mode === 'rebalance' && withComparison(plan.comparison, plan.request.power_params_ref)
    const stages: CpuStage[] = plan.mode === 'sweep' ? ['sweep']
      : ['rebalance', ...(cmp ? ['comparison' as const] : []), 'growth', ...(cmp ? ['growth-comparison' as const] : [])]
    begin(owner, plan.mode, stages)
    let outcome: CpuDone['outcome'] = 'ok'
    const failed: CpuStage[] = []
    publish({
      busy: true, error: null,
      ...(plan.mode === 'rebalance'
        ? { growthBusy: false, snapshotRequest: null, comparisonGrowth: null, comparisonGrowthError: null } : {}),
    })
    try {
      if (plan.mode === 'sweep') {
        const result = await adapter.sweep(plan.request, controller.signal)
        if (id === generation) publish({ result, keys: { ...state.keys, sweep: plan.key ?? null } })
        return
      }
      const result = await adapter.rebalance(plan.request, controller.signal)
      if (id !== generation) return
      // The previous comparison stays visible until the new main result arrives.
      publish({ rebalance: result, comparison: null, comparisonError: null, keys: { ...state.keys, rebalance: plan.key ?? null } })
      let comparison: CpuRebalance | null = null
      if (cmp) {
        step(owner, 'comparison')
        try {
          const response = await adapter.rebalance(onComparison(plan.request, plan.comparison!), controller.signal)
          if (id === generation) { publish({ comparison: response }); comparison = response }
        } catch (error) {
          failed.push('comparison')
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
      if (id === generation) failed.push(...await runGrowth({ ...plan.request, growths: plan.growths }, plan.comparison, id, plan.growthKey, owner))
    } catch (error) {
      outcome = 'error'
      if (id === generation) publish({ error: message(error) })
    } finally {
      if (id === generation) { publish({ busy: false }); finish(owner, outcome, failed) }
    }
  }
  return {
    getSnapshot: () => state,
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } },
    execute,
    cancel,
    /** User stop: like `cancel`, and the page is idle again (busy flags cleared, `done` = cancelled). */
    stop: () => {
      const p = state.progress
      cancel()
      const at = now()
      publish({ busy: false, growthBusy: false, ...(p ? { done: { mode: p.mode, outcome: 'cancelled' as const, at, ms: at - p.startedAt } } : {}) })
    },
    /**
     * Selection/mode transition: clears the sweep and the growth stage. A changed input selection
     * (`keepRebalance: false`) also drops the rebalance and growth results; errors, the comparison
     * and the busy flag are left to the next run, as before.
     */
    reset: ({ keepRebalance = false }: { keepRebalance?: boolean } = {}) => {
      ++growthToken
      growthController?.abort()
      // a standalone growth's progress ends with it; a sweep/rebalance workflow keeps reporting its own
      if (progressOwner?.startsWith('g')) { progressOwner = null; publish({ progress: null }) }
      publish({
        result: null, growthBusy: false, growthError: null, snapshotRequest: null,
        comparisonGrowth: null, comparisonGrowthError: null,
        keys: { ...state.keys, sweep: null, growth: null, ...(keepRebalance ? {} : { rebalance: null }) },
        ...(keepRebalance ? {} : { rebalance: null, growth: null }),
      })
    },
    clearHistory: () => publish({ runs: [] }),
  }
}
