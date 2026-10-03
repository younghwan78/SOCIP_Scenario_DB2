// "?" help text for the CPU what-if cards.
import type { ReactNode } from 'react'

export const CPU_HELP: Record<string, ReactNode> = {
  rbSetup: <>
    <b>MID cluster 사이에서 camera SW task를 어떻게 나눌지 계산합니다.</b>
    <ul>
      <li><b>pool</b> — task를 나눌 cluster. 기본은 BIG 계열을 뺀 cluster (camera SW에서 BIG 사용은 대체로 손해). 과제마다 MID 구성이 달라도 topology대로 표시됩니다 (E2600 MID_LF0/LF1/HF, 차기 MID_HF0/HF1).</li>
      <li><b>자동</b> — 계산이 pool 안에서 cluster를 고름 (cpuset 고정). <b>고정</b> — 지정 cluster. <b>제외</b> — 측정 위치 그대로.</li>
      <li><b>함께 이동</b> — 같은 group의 task는 같은 cluster로 (wakeup 지연·cache 공유가 큰 producer/consumer).</li>
      <li>같은 구성의 cluster 두 개(MID_HF0/HF1)는 바꿔도 결과가 같아 한 번만 계산하고, 표시는 덜 옮기는 쪽으로 합니다.</li>
      <li>분할 수가 30만 이하면 전부 계산, 넘으면 move/swap 국소 탐색 (전수 대비 0.1% 이내였음).</li>
    </ul>
  </>,
  rbCurve: <>
    <b>현재 배치에서 전력 이득이 가장 큰 task부터 하나씩 옮겨 본 경로입니다.</b>
    <ul>
      <li>한 cluster에 몰려 있으면 그 cluster OPP(V²f)와 DSU vote가 올라가고, 옮기면 받는 cluster의 전력이 올라갑니다 → U자 곡선의 바닥이 균형점.</li>
      <li>점선 = 전체 탐색의 최저 (곡선은 한 경로라 최저와 다를 수 있음). 흐린 막대 = budget 미충족.</li>
    </ul>
  </>,
  rbTop: <><b>budget을 만족하는 분배 중 CPU + DSU 전력이 낮은 순.</b> 상위 후보는 전체 EAS 모델로 다시 계산해 검증했습니다. MHz 색: 초록 = 현재보다 낮음, 빨강 = 높음.</>,
  rbStates: <><b>cluster OPP 조합이 같은 분배끼리 묶은 것.</b> 같은 OPP면 전력 차이가 1 mW 안팎이라 순위보다 “어떤 OPP 조합에 도달하느냐”가 중요합니다. 분할 수가 많을수록 그 상태로 가는 방법이 많다는 뜻.</>,
  rbBound: <><b>cluster를 OPP 한 단계 낮추는 데 필요한 util 감소량과 그만큼을 덜어 줄 수 있는 task.</b> 전압이 같은 구간이면 OPP를 낮춰도 이득이 작습니다 (mV 확인).</>,
  rbCross: <><b>같은 측정 profile을 다른 과제의 CPU 구성에서 재분배해 MID 구조 변경의 영향을 봅니다</b> (예: E2600 MID_LF0/LF1/HF → 차기 MID_HF0/HF1). 측정 cluster는 이름 → core type 순으로 대응하고, 대응이 없으면 기본 cluster로 보내며 경고를 표시합니다. task 고정(cluster 지정)은 비교 SoC에 적용되지 않고 ‘제외’만 유지됩니다.</>,
  rbSens: <>
    <b>architecture 단계 가정이 결론(권장 분배)을 바꾸는지 봅니다.</b>
    <ul>
      <li>DSU vote 표 ±1 step (즉시), SW 부하 증가 ×0.9 / ×1.2, schedutil margin 1.15 / 1.35, idle power gating 0.80 / 0.95 (각 2회 재계산).</li>
      <li>막대 = 최저 전력의 변화 폭. <b>바뀜</b> = 그 가정 범위 안에서 옮길 task·cluster 조합이 달라짐 → 그 가정을 먼저 확정해야 합니다.</li>
      <li>EM table · IPC 같은 topology 값은 power_model_params version을 바꿔 ‘과제 비교’로 봅니다.</li>
    </ul>
  </>,
  rbDetail: <><b>선택한 분배의 task별 배치와 시간.</b> 기기 적용 = 옮긴 task를 해당 cluster cpuset(또는 affinity)으로 고정.</>,
  dsu: <>
    <b>DSU 주파수를 정하는 규칙(가정)을 바꿔 보며 결론이 유지되는지 봅니다.</b>
    <ul>
      <li><b>vote 표</b> — busy cluster마다 자기 OPP에 대한 DSU 최소 주파수를 요청하고 DSU는 그 최대값으로 동작. architecture 단계에서는 가정값 (topology <code>cpu.dsu.vote</code>, <code>vote_source: estimate</code>).</li>
      <li><b>즉시 재계산</b> — DSU는 cluster 주파수·배치를 바꾸지 않으므로 표를 바꾸면 반환된 후보의 DSU 전력과 순위만 다시 계산. 전체 조합 순위가 필요하면 “이 규칙으로 다시 계산”.</li>
      <li><b>−1 / +1 step</b> — 표 전체를 DSU OPP 한 단계씩 내리고/올린 corner. 최적 배치가 바뀌면 그 가정을 먼저 확정해야 합니다.</li>
      <li><b>A / B</b> — 두 정책을 저장해 비교. <b>YAML 복사</b>로 topology에 붙여 넣어 팀 가정으로 등록.</li>
      <li><b>측정 고정</b> — 측정 residency를 모든 배치에 그대로 쓰는 예전 방식: 배치를 바꿔도 DSU 전력이 변하지 않아 재분배 이득을 과소평가합니다.</li>
    </ul>
  </>,
  input: <>
    <b>무엇을 기준으로 계산할지 고릅니다.</b>
    <ul>
      <li><b>측정 profile</b> — 실기기에서 측정한 task · thread별 CPU cycle, stall, bus 접근량과 cluster별 주파수 residency (PMU + Perfetto). frame 1장당 값으로 정규화되어 있습니다.</li>
      <li><b>적용할 SoC CPU 구성</b> — what-if를 돌릴 대상 SoC의 cluster 구성 · OPP · 전력 계수 (power_model_params). 차기 SoC 구성을 고르면 “같은 SW를 새 CPU에서 돌리면?”을 봅니다.</li>
      <li><b>profile을 측정한 SoC</b> — 측정 SoC와 대상 SoC가 다르면 고릅니다. core type(MID_LF / MID_HF / BIG…)으로 cluster를 대응하고 IPC 차이를 반영합니다.</li>
      <li><b>비교 기준 ★</b> — <code>현재 = 측정 배치</code>: 측정에서 실제로 돈 cluster에 그대로 둔 결과가 기준. <code>EAS 기본</code>: knob 없이 EAS가 스스로 배치한 결과가 기준.</li>
    </ul></>,
  cond: <>
    <b>계산 조건과 scheduler 모델 값입니다.</b>
    <ul>
      <li><b>fps</b> — frame 주기(= 1000/fps ms). 모든 task 시간 · 전력은 frame당으로 계산.</li>
      <li><b>SW 증가 배율</b> — 차기 과제에서 SW instruction이 늘어나는 비율(전체). task별 배율은 ③ 표의 “증가” 칸.</li>
      <li><b>idle power gating</b> — 일이 없는 core가 power-gate되는 비율(0–1). 높을수록 leakage 감소.</li>
      <li><b>CPU BW 배율</b> — CPU가 DRAM까지 내보내는 traffic 배율(L3/SLC 변경 what-if). BW 전력에 반영.</li>
      <li><b>scheduler 보정값</b> — schedutil <code>f = margin × util / capacity × fmax</code>의 margin, EAS fits_capacity margin, util_est / PELT 평균, PELT half-life, deadline boost(budget이 있는 task는 budget을 맞추는 OPP까지 올림), EM에 leakage 포함 여부. 비우면 topology 설정값을 씁니다. “모델 확인” 카드의 측정 vs 모델 MHz 차이가 크면 여기부터 조정합니다.</li>
    </ul></>,
  range: <>
    <b>어떤 task를 어느 cluster 후보로 sweep할지 정합니다.</b>
    <ul>
      <li><b>행 = SW task</b>, 괄호는 측정에서 돈 cluster. <b>칸 숫자</b> = 그 cluster fmax에서의 frame당 실행 시간(ms) · ✓ budget 충족 · ✗ 미충족 · ⚠ capacity 초과(EAS가 보내지 않음). 파란 칸 = 측정 위치.</li>
      <li><b>체크</b> = sweep 후보에 포함. 기본값은 budget을 맞추고 capacity에 맞는 cluster.</li>
      <li><b>knob</b> — 기기에서 실제로 바꿀 수 있는 것만: <code>cluster 고정</code>(cpuset/affinity로 한 cluster에 묶기), <code>상위 cluster 제외</code>(cpuset 상한), <code>uclamp.max</code>(주파수 상한 효과), <code>uclamp.min</code>(하한 boost).</li>
      <li><b>thr</b> = thread 수 (비우면 측정 thread 수). <b>budget ms</b> = frame당 허용 시간 (Timing Budget의 SW budget을 넣으면 그 안에 끝나는 배치만 “만족”). <b>증가</b> = 이 task만의 SW 증가 배율.</li>
      <li><b>(other)</b> — profile에서 어떤 task에도 매핑되지 않은 cycle(커널 · 다른 프로세스 · 이름 없는 thread 등). 정체를 모르는 부하라 옮기는 의미가 없어 <b>측정 배치에 고정</b>하고 sweep하지 않습니다 (의도된 동작). 전력에는 그대로 포함됩니다.</li>
      <li>thread 이름의 <code>#숫자</code>(예: <code>post_crta#2098</code>)는 측정 trace의 <b>thread id(TID)</b>입니다. 같은 task의 여러 thread를 구분하려는 것이며 표시는 “tid 2098”로 바꿔 보여줍니다.</li>
    </ul></>,
  cal: <>
    <b>모델이 측정을 재현하는지 먼저 확인합니다.</b>
    <ul>
      <li>측정 배치 그대로 EAS + schedutil을 돌렸을 때의 cluster 평균 MHz · util을 측정 residency · active 비율과 비교합니다.</li>
      <li>차이가 크면(예: ±20% 이상) 후보 순위도 믿기 어렵습니다 → ② scheduler 보정값(freq margin, util model, PELT)을 조정한 뒤 다시 계산하세요.</li>
    </ul></>,
  better: <>
    <b>★ 기준보다 CPU 전력이 낮으면서 조건(budget · capacity · frame 주기)을 만족하는 배치 후보입니다.</b>
    <ul>
      <li>막대 = cluster별 동적 + leakage + DSU + CPU BW 전력 합. 오른쪽 숫자 = ★ 대비 Δ.</li>
      <li>기본은 절감이 큰 <b>상위 5개</b>만 보여주고 “전체 펼치기”로 나머지를 봅니다. 행 클릭 = 아래 세부(적용 방법 · core 점유 · task 시간).</li>
      <li>“동등 N” = 같은 OPP · 같은 전력이 되는 다른 knob 조합 (어느 것을 적용해도 결과 동일).</li>
    </ul></>,
  detail: <>
    <ul>
      <li><b>적용 방법</b> — 후보를 기기에서 재현하는 knob (cpuset · affinity · uclamp 설정 위치).</li>
      <li><b>cluster · CPU 점유</b> — core별 util과 올라간 thread. boost 표시는 deadline boost로 schedutil 주파수보다 올린 경우.</li>
      <li><b>task 표</b> — ★ 대비 배치 · 시간 변화와 budget slack. slack &lt; 0.5 ms는 주의(빨강).</li>
    </ul></>,
  others: <>전력이 ★보다 높거나 조건을 만족하지 못한 조합입니다. 정렬해서 “왜 이 배치는 안 되는지” 확인할 때 씁니다.</>,
}

/** "post_crta#2098" → "post_crta · tid 2098" (numeric thread part = Linux TID from the trace). */
export function threadLabel(s: string): string {
  const [task, thread] = s.split('#')
  if (!thread) return s
  return /^\d+$/.test(thread) ? `${task} · tid ${thread}` : `${task} · ${thread}`
}
