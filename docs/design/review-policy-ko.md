# 과제 review policy — fps 유지 · 전과제 대비 소비전류 · 발열 대응 (P0, 2026-10-09)

고객 요구 (사내 형식):
1. **fps drop 불가** — timing 판정 fail / 출력 간격 이탈 = 높은 위험. latency 증가는 보고만 (한도는 선택).
2. **소비전류는 전과제와 유사 혹은 낮게** — 같은 variant의 전과제 값 대비 ≤ 0 % 양호, ≤ +tolerance % 유사, 초과.
3. **발열은 board 의존** — UHD120 · Pro video · UHD portrait처럼 power 감소 요청이 잦은 scenario는
   미리 "어떤 lever로 얼마나 줄일 수 있는지"를 계산해 둔다.

## 설정 위치 — `project.globals.review_policy` (선택, 없으면 이전 동작)
```yaml
globals:
  review_policy:
    throughput_model: pipelined      # NRT/Post 판정: M2M buffering, fps = 출력 간격 (없으면 stage)
    register_baseline: iq_keep       # 기본 등록 = lossy·가정 ratio 없는 최저 power (없으면 min_power)
    max_latency_frames: 3            # (선택) buffering latency 한도
    power_reference:
      project_ref: proj-<전과제>     # 같은 DB의 전과제, variant id로 매칭
      values_mw: {cam-rec-r1-uhd120: 2000}   # 전과제가 DB에 없을 때 직접 지정
      source_priority: [explicit, measurement, prediction]  # 기본값. measurement = silicon 실측만, 합성 실측은 항상 마지막
      tolerance_pct: 3
    sw_growth_budget: 1.2            # (선택) 차기 SW 증가 예산 — 1쪽 요약 조건에 표시
    kpi:                             # (선택) 1쪽 요약 KPI 목록 (없으면 thermal_watch + 전과제 기준 variant)
    - {variant_ref: cam-rec-r1-uhd30-vdis, label: UHD30 VDIS, tier: base}
    - {variant_ref: cam-rec-apv-uhd60-422-sdr, scenario_ref: uc-cam-recording-apv-e2600, label: APV UHD60, tier: thermal}
    thermal_watch:
    - {scenario_ref: uc-cam-recording-e2600, variant_ref: cam-rec-r1-uhd120, label: UHD120 video, reduction_pct: [10, 20]}
```
E2600 (사외 fixture): `values_mw`는 **SAMPLE 가상 값** — 사내에서는 `project_ref`로 대체.

## 적용 범위
| 기능 | 동작 |
|---|---|
| Timing Budget · Fleet · DVFS what-if · 조합 탐색 | 요청에 `throughput_model`이 없으면 policy 값 (UI 토글에 "과제 기준" 표시, URL `tp`로만 override). run spec에 저장 → input hash 반영 |
| 예측 등록 | `register_baseline: iq_keep` → 규칙 `auto:min-power-iq` (tier A best). lossy 최저 조합은 "최저 power (lossy)"로 선택 가능 |
| 예측 현황 · Risk | 전과제 대비 (초과=높음, 유사=중간), stage 기준으로 등록된 예측 경고, latency 한도, SW 여유 (pipelined = period − 최장 SW task, RT 제외) |
| 예측 현황 · 발열 대응 | `GET /review/thermal-watch`: 기준 = 화질 유지 최적, lever = IP clock ↓(fps 유지 시만) → lossy compression → power option, −10/−20 % 요청별 조합 · 충족 여부 · IQ 평가 필요 여부 |
| API | `GET /review/references?project_ref=` (policy + variant별 전과제 값), `GET /review/thermal-watch?project_ref=&config_profile_ref=` |

## 계산 규칙 · 한계
- 감소 lever 합은 항목 효과의 합(근사). option 효과는 lossy 최저 조합 기준 단독 효과(조합 탐색 `power_options.marginal`).
- 화질 유지 조합이 없으면 자동 등록을 건너뛴다. 손실 압축 조합은 사유를 입력해 명시적으로 선택한다.
- 전과제에서 같은 variant ID가 여러 scenario에 있으면 자동 매칭하지 않는다. 직접 지정한 reference 값은 사용할 수 있다.
- 발열 watch의 scenario/variant는 선택한 과제에 속해야 하며, DVFS 기준 power가 watch 기준과 다르면 절감량 합산에서 제외한다.
- IP clock ↓는 domain별 L−1/L−2를 다시 계산해 fps를 지키는 것만 사용 (E2600 watch 3종은 이미 최소 level → 전부 fps drop).
- 요청을 IQ lever로도 못 채우면 "성능 조건 변경(해상도 · fps · EIS) 필요"로 표시 — fps는 자동으로 낮추지 않음.

## 과제 검토 보고서 판정 (2026-10-18)
| 항목 | 규칙 |
|---|---|
| 전과제 대비 판정 (REF-05) | 현 과제 silicon 실측이 있으면 실측으로 판정, 예측과 허용선 기준 반대면 **불일치**(verdict_flip, High). 예측이 이하여도 탐색 범위 상단 · 보정 예측(예측 ÷ (1 + 실측 대조 total median), 체계 오차 · 5건 이상일 때) · 합성 실측이 허용을 넘으면 **조건부**(Medium). 미등록 variant는 탐색값으로 판정하고 "미등록" 표시 |
| risk 유효성 (RISK-01) | `confirmed` · `model_limit`(120 fps 이상 NRT batch 미모델 등) · `input_unverified`(`sensor_support: unverified*`, SW timing 가정값으로 인한 SW 미달). Critical은 confirmed에만 — 나머지는 High "검증 필요". risk마다 `checks`(먼저 확인할 항목) |
| SW margin 건수 | spec 만족 전체 variant 기준 (Top-5 표와 무관) |
| 전력 절감 순서 | ① 최적 clock(DVFS 최소 level · RT 최소 clock) → ② compression(lossless · LLC → lossy) → ③ SW 최적화(task · CPU 배치) → ④ 화질 열화 option(MTNR L0 skip · LowPower 등)은 마지막, IQ 평가 후에만. 권고 조치 · 완화안 · 1쪽 요약이 같은 순서 |
| 화질 | power option IQ 검토 상태(candidate · iq_eval · adopted · rejected)를 보고서에 고정. 발열 표는 확정 절감(DVFS + IQ 승인)과 IQ 평가 포함 최대를 나눠 표시 |
| 1쪽 요약 (Tier 0) | 과제 조건(SoC · board · sensor · SW · DVFS · 전과제 기준) · scenario coverage(파생 sub-variant 제외) · KPI scoreboard · 메시지 3 · Top risk · 결정 요청 · 절감 순서 |
