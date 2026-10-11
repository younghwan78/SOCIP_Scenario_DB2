# 조합 탐색 Lever 분석 · CPU what-if Timing 연동 (2026-10-11)

## 1. 조합 탐색 — Lever 분석 (engine `arch-exploration/11`)

### 바뀐 점
| 항목 | 이전 | 현재 |
|---|---|---|
| 압축 후보 | buffer당 1개 mode (기본 lossy만) | buffer마다 off / lossless / lossy를 따로 탐색 (`CompressionAxis.modes` 기본 `["lossless","lossy"]`) |
| lossless ratio | catalog `comp_ratio` 1.0 (worst-case) → 후보 제외 | SoC catalog `typical_ratio`(평균, power 용) 사용, `comp_ratio`는 BW 할당용 worst-case로 유지 |
| case key | `c=PYRAMID_L0+PYRAMID_L1` | `c=PYRAMID_L0:LL+PYRAMID_L1:LY` (+ `compression_modes`) |
| 결과 | 최저 power n개 + tier | `levers`: lever별 효과 · IQ 우선 경로 · 설계 조합 분포 |

### `summary.levers`
- **IQ class**: `neutral`(lossless SBWC), `eval`(IP mode · knob, IQ 평가 필요), `trade`(lossy)
- **steps**: baseline에서 neutral → eval → trade 순으로 남은 lever 중 가장 큰 절감을 하나씩 추가
  - 각 단계 total은 실제 평가된 설계 조합에서 조회하므로 상호작용이 반영됨 (예: L0 skip 후 L0 압축은 무효)
- **milestones**: 단계별 끝 상태 (`neutral` = 화질 무손실 최적 = `tiers.keep.best`)
- **levers[]**:
  - `alone`: baseline에 이 lever만 켰을 때의 Δ (CPU / IP / BW / MB/s)
  - `in_context`: 경로 끝 조합에서 on/off한 Δ
  - `moot`: 최종 option이 이 buffer를 없앰
  - `overlap`: 단독 효과와 차이가 큼
- **points**: option 조합 × 압축 선택 전체. 기준은 objective SW, 해석 DVFS level
- **sw_band_mw**: SW 통계 × 증가율 폭 (설계 선택이 아니라 불확실성)
- **costs**: DVFS +1 level 비용 (성능 여유용)

### UI (조합 탐색 → variant 상세 첫 카드 "Lever 분석")
- tile: baseline / 화질 무손실 최적 / + IQ 평가 / + lossy / 실측 (coverage의 대표 측정)
- IQ 우선 경로 waterfall, Power 분포 (IQ class별 lane, SW 띠, baseline · 실측 선), lever 표

### Exynos2600 fixture 보강 (SAMPLE)
- MLSC 0.6, GDC 1.2, VPS 0.8 mW/MP: 미모델 IP를 0 mW로 두지 않기 위함
- MFC `LowPower` mode: 8K PSM의 `mfc_enc`가 clock/power 0이던 문제
- `COMP_YUV_LOSSLESS` typical 0.7, `COMP_BAYER_LOSSLESS` typical 0.75
- 모두 사내 실제 계수로 교체할 대상

## 2. CPU what-if — Timing Budget 연동

- `POST /cpu/rebalance`의 `timing_coupling: "off" | "stage_slack"`, `timing_statistic`
  - 측정 profile의 scenario variant로 Timing Budget을 계산
  - SW item이 있는 stage마다 `stretch = max(1, (P − HW − overhead) / SW)`
  - 해당 task의 budget = 측정 배치의 task 시간 × stretch
  - 결과: 모델의 stage SW 시간 증가를 여유 범위로 제한. 기존 timing 실패를 해결하거나 전체 fps/latency를 보증하지는 않음
- `off`여도 `timing_coupling.impact`(측정 배치 / 최적 배치의 stage SW Δ, 여유, +latency frame)는 계산
- `RebalanceSpec.stretch_budgets`: anchor는 측정 배치의 task 시간
  - 탐색은 per-cluster 추정과 full evaluate 중 큰 값을 사용하며, 최종 검산은 full evaluate 기준 제한을 적용
  - 사용자 지정 budget과 stage 제한 중 더 엄격한 값을 적용하고 최종 feasible 후보만 선택
- `result.why`: cluster별 OPP(f, V) 변화, DSU, 이동 task와 시간 변화, 늘어난 task, OPP를 내리는 데 필요한 util
- UI: 결과 첫 카드 "왜 이 분배인가 · SW timing 영향"
  - `SW 여유 제약 | CPU 주기만` 전환 (기본 SW 여유 제약, `cpu.rb.timing`)
  - inline CPU profile은 stage 연동 불가, CPU fps와 scenario fps가 다르면 연동 요청 거부
  - Timing Budget 기준은 scenario SW 통계에 task별 growth를 적용한 모델 값이며, CPU profile의 관측 시간과 동일한 값이라는 의미는 아님

## 등록 조건과 근거 보존
- 재구성한 압축 조합에도 원래 탐색의 timing, power, BW 제약과 탐색 buffer 범위를 적용
- IQ option은 평가한 dimension의 값만 선택 가능. 중복 IQ 결과나 공백 근거는 거부
- 적용 option은 run spec과 prediction 조건에 보존하며 freshness는 같은 option을 적용한 입력으로 비교
- option 적용 예측의 조건 링크는 적용 run을 다시 열고, 자동 재계산은 재선택이 필요하다고 표시

## 3. 해석 주의
- lossless typical ratio, SAMPLE unit power, synthetic MTNR LowPower는 off-site 예시 값
- L0 skip은 BW만 줄고 MTNR 연산량(IP power)은 줄지 않게 모델돼 있음 → IP 절감은 과소평가
- UHD30 VDIS의 VDD_CAM은 CSIS(전압표 없음 → 710 mV 기준값)가 rail을 잡음
  - CAM IP가 L7(618.75 mV)에서도 710 mV로 계산됨
  - CAM +1 level 비용이 0 mW로 보이는 이유
- CPU stretch는 stage 안 모든 SW task가 같은 배수로 느려진다는 보수적 분배임
