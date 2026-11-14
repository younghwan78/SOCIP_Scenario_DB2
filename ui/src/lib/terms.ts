/** U-11: one vocabulary for verdicts and bases. Each family has its canonical badge words; the aliases are
 * the other words that were used for the same thing (search finds them, the UI should not show them). */
export interface TermEntry {
  id: string
  /** the term as the UI shows it */
  term: string
  family: '판정' | '기준' | '결과' | '대상'
  /** canonical badge / state words, in order */
  states?: string[]
  meaning: string
  /** words not to use for this (older or mixed wording) */
  avoid?: string[]
  where?: string
}

export const TERMS: TermEntry[] = [
  { id: 'timing-verdict', term: 'Timing 판정', family: '판정', states: ['OK', 'Clock ↑', 'Fail', '판정 미지원'],
    meaning: 'RT 출력 간격 · stage 예산을 지금 clock으로 맞추는지. Clock ↑ = 규칙 clock보다 올려야 맞춤. 판정 미지원 = 판정할 RT 출력이 없는 scenario.',
    avoid: ['pass', 'NG', 'timing 판정 미지원(표에서 길게)'], where: 'Timing Budget · Timing fleet · 탐색 spec 열' },
  { id: 'spec', term: 'spec 판정', family: '판정', states: ['충족', '미달', '판정 미지원'],
    meaning: '탐색 조합이 그 variant의 spec(timing 판정 + 설정된 제약: SW 증가 허용 · peak BW · footprint …)을 모두 만족하는지. 미달이면 첫 사유를 행에 표시합니다.',
    avoid: ['spec OK / Fail', '만족', 'pass'], where: '조합 탐색 · 결론 카드 · power option' },
  { id: 'verified', term: '검증', family: '판정', states: ['✓ 일치', '✗ 불일치'],
    meaning: '추천 조합을 timeline으로 다시 시뮬레이션해 해석식 결과(power · BW)와 허용 오차 안에서 일치하는지. 모델 내부 교차 확인이며 실측 검증이 아닙니다.',
    avoid: ['silicon 검증', '실측 확인'], where: '조합 탐색 검증 열 · 결론 카드' },
  { id: 'eligible', term: '등록 가능', family: '판정', states: ['등록 가능', '등록 불가'],
    meaning: 'spec 충족이고 검증에서 실패하지 않은 조합 — 예측으로 등록할 수 있는 대상.',
    avoid: ['eligible'], where: '결론 카드 · 등록 버튼' },
  { id: 'target', term: '목표', family: '판정', states: ['목표 충족', '목표 미달'],
    meaning: 'power 감소 요청(예: −10 %)이나 What-if 목표를 이 조합이 달성하는지.', where: '목적 front · What-if sweep' },
  { id: 'cpu-fit', term: 'CPU 배치 판정', family: '판정', states: ['충족', '조건부', '대기 미충족', '미충족', '자체 충족'],
    meaning: '다른 cluster · 주파수에 task를 배치했을 때 budget(slack)을 지키는지. 충족 = 우선순위(task_policy)로 같은 CPU 대기까지 넣어도 충족, 조건부 = 자체 실행시간으로는 충족이지만 우선순위가 없어 같은 CPU co-runner를 모두 기다리면 초과, 대기 미충족 = 우선순위를 넣은 대기로 초과, 미충족 = 자체 실행시간으로도 초과, 자체 충족 = 대기를 확인하지 않은 자체 실행시간 판정.',
    where: 'CPU what-if' },
  { id: 'iq', term: '화질 유지 / 화질 trade', family: '결과', states: ['화질 유지', '평가 필요', '화질 trade'],
    meaning: '조합이 화질을 바꾸는지. 화질 유지 = 무압축 · lossless, 평가 필요 = power option처럼 IQ 평가가 필요, 화질 trade = lossy 포함(사유 필요).',
    avoid: ['keep / trade(영문 그대로)'], where: '조합 탐색 후보 표 · 레버 선택' },
  { id: 'baseline', term: 'baseline', family: '기준',
    meaning: '같은 variant의 지금 설정(탐색 전 기본 조합). "baseline 대비"는 추천 조합 − baseline.',
    avoid: ['기준(단독)', 'reference'], where: '조합 탐색 · What-if' },
  { id: 'power-reference', term: '전과제 기준', family: '기준',
    meaning: '과제 정책(review_policy)의 power reference — 이전 과제 같은 variant의 값. "전과제 대비"는 추천 조합 / 전과제 기준.',
    avoid: ['baseline', 'reference(단독)'], where: '조합 탐색 · 검토 보고서' },
  { id: 'anchor', term: '★ 기준 variant', family: '기준',
    meaning: '비교 표에서 다른 행의 Δ를 재는 행. 정렬과 무관하게 맨 위에 고정됩니다.', avoid: ['baseline'], where: 'Explorer · Compare' },
  { id: 'model-basis', term: '모델 기준', family: '기준',
    meaning: '계산에 쓴 config profile(모델 정의 + 가정값) 버전. 기준이 다르면 결과를 직접 비교하지 않고 경고합니다.', where: 'What-if · 조합 탐색 · 예측 현황' },
  { id: 'prediction', term: '예측', family: '대상',
    meaning: 'variant의 검토 기준으로 등록한 계산 결과. 탐색의 추천값과 구분합니다.', avoid: ['미등록 추천값을 예측이라고 부르기'], where: '예측 현황 · 보고서' },
  { id: 'recommendation', term: '추천', family: '대상',
    meaning: '탐색 run 안에서 spec 충족 조합 중 과제 정책(기본: 최저 power)으로 고른 조합. 등록 전에는 예측이 아닙니다.', where: '조합 탐색' },
  { id: 'evidence', term: 'Evidence', family: '대상',
    meaning: '측정 또는 simulation 결과와 그 출처. 합성 측정이나 모델 예측을 물리 측정의 검증으로 보지 않습니다.', where: 'Evidence · 보정' },
  { id: 'assumed', term: '가정값', family: '대상',
    meaning: 'value_source: assumed — 실측 · datasheet 근거 없이 넣은 값. 민감도(tornado)에서 영향이 큰 가정값부터 확인합니다.', where: '모든 계산 근거' },
]

export const termById = (id: string) => TERMS.find((t) => t.id === id)

export const termHref = (id: string) => `#/library?tab=terms&sel=${encodeURIComponent(id)}`
