import { useEffect, useState, useSyncExternalStore } from 'react'
import { loadPref, savePref } from '../components/Layout'
import { cpuApi } from './cpu'
import { createCpuAnalysis, type CpuAnalysisAdapter, type CpuRun } from './cpuAnalysis'
import { sweepApi } from './growthSweep'
import { rebalanceApi } from './rebalance'

const http: CpuAnalysisAdapter = {
  sweep: (request, signal) => cpuApi.sweep(request, signal),
  rebalance: (request, signal) => rebalanceApi.run(request, signal),
  growth: (request, signal) => sweepApi.run(request, signal),
}

/** React/storage wiring; all execution and result ownership lives in the analysis module. */
export function useCpuAnalysis() {
  const [analysis] = useState(() => createCpuAnalysis(http, loadPref<CpuRun[]>('sdb.cpu.runs', [])))
  const state = useSyncExternalStore(analysis.subscribe, analysis.getSnapshot)
  useEffect(() => savePref('sdb.cpu.runs', state.runs), [state.runs])
  useEffect(() => () => analysis.cancel(), [analysis])
  return { analysis, state }
}
