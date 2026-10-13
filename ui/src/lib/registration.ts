import { useState } from 'react'
import { ApiError } from './api'
import { archApi, type BoardRow, type CurrentPredictionGuard } from './archExplore'
import { useAsync } from './route'

export function currentGuards(targets: { scenario_id: string; variant_id: string }[], rows: BoardRow[]): CurrentPredictionGuard[] {
  const current = new Map(rows.map((row) => [`${row.scenario_id}|${row.variant_id}`, row.id]))
  return targets.map((target) => ({ scenario_id: target.scenario_id, variant_id: target.variant_id, prediction_id: current.get(`${target.scenario_id}|${target.variant_id}`) ?? null }))
}
/** Read the current IDs when reviewing a candidate, then require explicit refresh after a conflict. */
export function useRegistrationGuard(targets: { scenario_id: string; variant_id: string }[], project?: string | null, reviewKey = '') {
  const [tick, setTick] = useState(0)
  const [conflict, setConflict] = useState(false)
  const key = targets.map((target) => `${target.scenario_id}|${target.variant_id}`).join(',')
  const q = useAsync(() => archApi.board(undefined, project || undefined).then((board) => currentGuards(targets, board.rows)), [project, key, reviewKey, tick])
  return {
    expected: q.data, ready: !!q.data && !conflict, error: q.error, conflict,
    refresh: () => { setConflict(false); setTick((n) => n + 1) },
    fail: (error: unknown) => {
      if (error instanceof ApiError && error.status === 409) {
        setConflict(true)
        return '검토하던 기준 예측이 변경되었습니다. 예측 현황에서 새 결과를 비교하고 기준을 다시 확인한 뒤 재계산·등록하세요.'
      }
      return error instanceof Error ? error.message : String(error)
    },
  }
}
