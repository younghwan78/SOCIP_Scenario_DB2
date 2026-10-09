# UX 피드백 반영 (2026-10-09)

| 페이지 | 피드백 | 반영 |
|---|---|---|
| Scenario | sim tooltip이 "evidence 1"뿐 | `GET /calibration/coverage`에 `simulations[]` (날짜 · tool version · source · SW · total mW, 최신순 · `shown`) 추가, 배지에 최신 날짜 표시 |
| Scenario | 등록 예측 key 전체 노출 | 짧은 key (`PRED-3fa9c…`) + `v<n>` (해당 variant의 n번째 등록) + 등록일 · 선정 규칙 · run · 대체 이력 |
| Scenario | 실측 등록 정보 | `measurements[]` (측정일 · 실측/합성 · silicon · SW · build · power) — `shown` = 대표 (최신 실측 → 합성) |
| 공통 | mA@Vbat 병기 | `mA = mW ÷ Vbat ÷ PMIC 효율`, 값은 과제 sim config profile `run_config.vbat / pmic_efficiency` (기본 4.0 V · 0.85) — `ui/src/lib/battery.ts` |
| Pipeline · IP 내부 | stat이 점선이라 다른 전달 방식처럼 보임 | 선 = 전달 경로 (OTF 얇은 파랑 · DMA 굵은 주황 · SW 점선 보라), 칸 색 + tag = 데이터 (IMG · STAT · HIST · TRIG). stat WDMA = 주황 실선 + STAT |
| Pipeline · Sequence tooltip | Timing 괄호 · 의미 | 시작 / 소요 / 범위 · frame 수 / 끝을 줄 단위로, 하단에 값 정의 |
| Pipeline · 표 | 기본 순서 | Sequence 순서(`sequenceOrder`, `#` 열)로 기본 정렬 (DMA 표는 producer 기준) |
| Pipeline · 표 | IP별 실측 BW 비교 | `GET /calibration/ip-bandwidth` — 예측 = 최신 simulation DMA port BW의 IP 합, 실측 = `metric_observations` `bandwidth.read/write/total` scope `ip` (ref = node id 또는 HW 이름, 대소문자 무시). R/W 별도 · total만 있으면 R+W로 비교. `bandwidth.total`에 scope `ip` 허용 |
| Compare | 주요 원인 가독성 · mA | 원인별 한 줄 (종류 · 이름 · ±Δ · mA · 막대), 표의 mW 행에 mA |
| Timing Budget | buffering pipeline | `throughput_model: pipelined` (UI 기본): NRT/Post HW = IP rule clock, 각 SW task가 1 frame 안이면 OK, SW+HW 합이 period를 넘으면 latency만 증가 (verdict note). `stage` = 이전 기준 |
| Timing Budget | 현재 clock의 SW 여유 | KPI "SW 여유 · 현재 clock" (RT/NRT/Post) |
| Timing Budget | level ±1/±2 → BW/power | `POST /timing-budget/dvfs-whatif` + ⑦ 카드: domain(CAM/INTCAM/INT)별 L±1·L±2 고정 재계산 → 판정 · ΔmW · ΔmA · IP/BW Δ · stage별 여유 Δ · latency |
| 예측 현황 | risk · focus | ① Risk · Focus 카드: 성능(판정 · SW 여유) / 발열(고객 목표 mW, URL `target`) / 신뢰도(실측 · sim 검증 · range) → 먼저 볼 것 (power option · CPU · IP clock · BW · 실측) — `ui/src/lib/predRisk.ts` |
| 조합 탐색 | 화질 유지 vs power 우선 · L0 bypass 독식 | `tiers.keep` = lossy/가정 ratio 없는 최적 + ±3% 조건 범위(DVFS level · compression), `tiers.trade` = lossy 허용 최적. `power_options.marginal` = option별 단독(조건부) 효과, 항상 이득인 option은 `fixed` → 조합 표에 "고정 대비" 열 |
| CPU what-if | 용도 | 상단 3질문 패널 (현재 SW 재배치 이득 · traffic shaping · 차기 구조/SW 증가) + 실행 기록 비교 |

## 데이터 형식 — IP 단위 BW 실측
```yaml
metric_observations:
- metric_id: bandwidth.read      # bandwidth.write / bandwidth.total
  scope: {kind: ip, ref: MTNR}   # node id 또는 HW 이름
  unit: MB/s
  stats: {mean: 2016.6, p95: 2137.6}
```
E2600 합성 예시: `meas-synth-baseline-cam-rec-r1-{uhd30-vdis,8k30-psm}` (`scripts/generate_baseline_evidence.py::ip_bw_observations`).

## 한계
- IP clock level은 IP core power만 바꿈 (DMA MB/s 불변, MIF DVFS 미모델).
- Risk 규칙은 heuristic (SW 여유 10%, 목표 90%, range 25%).
- tier ±3% 범위 · option 단독 효과는 objective slice(SW 통계 · 증가 배율) 기준.
