import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { LeverAnalysisView } from './LeverAnalysis'
import type { LeverAnalysis } from '../lib/archExplore'

const base = { total_mw: 100, cpu_mw: 0, hw_mw: 100, bw_mw: 0, bw_mbs: 1000 }
const ms = { total_mw: 89, bw_mbs: 900, delta_mw: -11, delta_pct: -11, options: [], compression: { A: 'COMP_YUV_LOSSLESS' } }

it('renders a reference-only analysis with a warning and the exact optimum when the greedy path stops short', () => {
  const la: LeverAnalysis = {
    status: 'reference', baseline_eligible: false, baseline: base, levers: [], steps: [],
    milestones: { neutral: { ...ms, gap_mw: 9, greedy_suboptimal: true } },
    optimum: { neutral: { options: [], comp: { B: 'COMP_YUV_LOSSLESS', C: 'COMP_YUV_LOSSLESS' }, iq: 'neutral', total_mw: 80, bw_mbs: 800, delta_mw: -20 } },
    points: [], point_count: 0,
  }
  const html = renderToStaticMarkup(<LeverAnalysisView la={la} battery={{ vbat: 3.85, eff: 0.85, source: 'test' }} />)
  expect(html).toContain('참고용')
  expect(html).toContain('정확 최적은 80.0 mW')
  expect(renderToStaticMarkup(<LeverAnalysisView la={{ status: 'none' }} battery={{ vbat: 3.85, eff: 0.85, source: 'test' }} />)).toContain('lever 분석이 없습니다')
})
