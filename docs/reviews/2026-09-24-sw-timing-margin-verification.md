# SW timing margin — 구현 검증 (2026-09-24)

Branch `feat/sw-timing-margin` (base `main` 3ea825c). 가이드: [guides/sw-timing-margin.md](../guides/sw-timing-margin.md)

## 변경 요약

| 파일 | 내용 |
|---|---|
| `src/scenario_db/sim/sw_margin.py` | 분석 모듈: 입력 모델(TimingStat, IpSerialOverhead, SwGrowth, ExtraSwTask, constraints), C1/C2 평가, robust m* solver, per-IP plan, growth headroom/sweep, critical-path 분해, Monte Carlo |
| `src/scenario_db/sim/runner.py` | timeline task `serial_overhead_ms`를 HW duration에 가산 (키 없으면 기존 동작 동일) |
| `src/scenario_db/api/{schemas,routers}/simulation.py`, `sim/service.py` | `POST /simulation/sw-margin` (analyst+, read-only, config profile·DVFS table·SW projection 검증 재사용, MC ≤ 50) |
| `scripts/sw_margin_report.py` | fixture variant 일괄 보고서 (JSON/Markdown, Top5, 권고) |
| `tests/unit/sim/test_sw_margin.py`, `tests/unit/api/test_sw_margin_api.py` | 14 tests |

## 검증

| 항목 | 결과 |
|---|---|
| 신규 test (14) | pass |
| `tests/unit` 전체 | 신규 포함 pass. 실패 11건은 환경 원인(작업 VM): legacy_import 10건 = 연결 폴더 파일 삭제 권한 없음, perfetto 1건 = trace_processor 다운로드 차단. 변경 코드와 무관 |
| ruff check / format (신규 파일), mypy (`sw_margin.py`) | pass |
| 경계 검증 | m*에서 feasible, m*−0.003 infeasible (fhd60-sdr) |
| 해석해 검증 | latency 완화 시 C1만 binding → m* = 1 − (P − overhead)/((1+h_blank)P) (uhd30-vdis, ±0.003) |
| 단조성 | SW growth ×1.0/1.3/1.6 → m* 비감소 |
| Extra task | 전용 core: 후행 MTNR 시작 +3.000 ms 정확, 공유 CPU: 최악 frame +7 ms (contention) |
| Critical path | HW+SW+overhead+wait = latency (±0.01 ms) |
| Monte Carlo | seed 고정 재현, sample m* ≤ max-statistic m* |
| 읽기 전용 | graph/variant 불변, DB add/commit 없음 |
| 버그 수정 | SW duration 0 (growth scale 0)에서 timeline critical-path walk 무한 대기 → SW task duration 하한 1e-6 ms |

## Fixture 결과 (uc-camera-recording 61 variant, statistic=max)

가정: IP 직렬 overhead setup 0.5/1.0/2.0 + completion 0.3/0.6/1.5 ms (min/mean/max, sensor 동기 RT 제외 HW), latency budget 3 frame (display), DVFS 없음, SW timing은 fixture `assumed` 값. 소요 240 s (≈ 4 s/variant).

| Verdict | 수 | Variant |
|---|---:|---|
| rule_over_provisioned | 37 | 30fps 단일 카메라 대부분 (FHD/UHD/8K, dual/triple 30fps, front 30fps) |
| rule_adequate | 6 | r1-uhd60-sdr/hdr10, rdual/rtriple-uhd60, f1-fhd60/uhd60 |
| rule_insufficient | 5 | r1-fhd60-sdr/hdr10, r1-uhd60-psm, rdual/rtriple-fhd60 (m* 25.8–26.6%, display latency binding) |
| clock_unreachable | 6 | fhd60/uhd60-supersteady (SW 경로), rcv/pip ×4 (MCSC 등 2-stream 공유 IP 과부하) |
| infeasible | 7 | 120/240/480/960 fps: per-frame SW 모델 → CPU_CAMERA C1 위반 (batch 모델 필요) |

### 대표 결과

| Variant | overhead | stat | m* | HW limit ms | Rule | Headroom @rule | SW+ovh share | Binding |
|---|---|---|---:|---:|---|---:|---:|---|
| r1-uhd30-vdis | 없음 | max | 4.7% | 33.36 | over (+20.3%p) | ×2.1 | 23% | C1 MCSC (h_blank floor) |
| r1-uhd30-vdis | 가정 | max | 14.7% | 29.86 | over (+10.3%p) | ×2.0 | 34% | C1 NRT group + MFC |
| r1-fhd30-vdis | 가정 | max | 14.7% | 29.86 | over | ×1.15 | 27% | C1 DPU |
| r1-fhd60-sdr | 가정 | max | 26.6% | 12.85 | insufficient | ×0.95 | 34% | C2 display 50 ms |
| r1-uhd60-sdr | 가정 | max | 24.7% | 13.18 | adequate | ×1.0 | 42% | C1 MCSC |
| r1-fhd60-supersteady | 없음 | mean / max | 17.3% / 50.4% | 14.47 / 8.67 | over / insufficient | ×1.1 / ×0.7 | 21% / 32% | C2 display |
| r1-fhd60-supersteady | 가정 | max | 84.4% | 2.73 | clock_unreachable | ×0.5 | 53% | C2 display |
| pip-uhd30 | 가정 | max | 57.8% | 14.79 | clock_unreachable | HW-only 불가 | 31% | C1 MCSC (2 stream) |

- 30fps 단일 stream: pipeline이 SW를 HW와 겹쳐 실행하므로 필요한 margin은 **h_blank + IP 직렬 overhead** 수준 (overhead 없으면 4.7%, 3.5 ms 가정 시 14.7%). 25% rule은 10–20%p 과설계 → DVFS table 연결 시 clock/전압 하향 여지
- 60fps: display latency(3 frame = 50 ms) 안에 SW(post_crta+pre_me_rta+post_irta+eis ≈ 16 ms, max) + overhead가 들어가야 해 m*가 25%를 넘거나 근접. growth headroom ×0.95–1.0 → **차기 SW 증가 시 바로 위반**
- SuperSteady 60fps (max stat): SW+overhead가 critical latency의 53% → clock으로 해결 불가, SW 단축 또는 latency budget 재정의 필요. mean stat이면 17.3% → **statistic 선택이 결과를 좌우** (Monte Carlo 20 sample: p50 37.9%, p90 48.8%, rule coverage 0%)
- PIP/RCV: 두 stream이 MCSC 등을 time-multiplex → rule 25%로는 HW만으로도 C1 위반. per-stream rule이 아니라 공유 IP load 기준 검토 필요

### 차기 과제 시나리오 예 (runtime ×1.2 + 신규 SW task 1.5/2.0/3.0 ms, post_irta→mtnr)

| Variant | 현재 m* | 차기 m* | 결과 |
|---|---:|---:|---|
| r1-uhd30-vdis | 14.7% | 14.7% | C1 binding 유지, display latency 76.97 → 83.79 ms (budget 100) — SW 증가는 latency slack이 흡수 |
| r1-fhd60-supersteady | 84.4% | 불가 | CPU_CAMERA load 18.1 > 16.7 ms/frame + latency 76 ms > 50 ms → SW core 분리/최적화 필수 |

## 한계 및 후속

| # | 항목 |
|---|---|
| 1 | IP 직렬 overhead는 가정값 → 이전 과제 Perfetto에서 IP별 setup(trigger→HW start) / completion(HW done→IRQ 처리 끝) 추출 adapter 필요 (`meas_import` 연계) |
| 2 | SW timing은 fixture `assumed` → 측정 evidence 기반 `sw_timing_projection` 입력으로 교체 (API는 지원, DB 필요) |
| 3 | CPU core affinity/priority/CPU DVFS 미모델, per-frame spike는 MC 지속값 근사 |
| 4 | 고fps batch 처리(`batch_size`) 미모델 → 120fps 이상 infeasible 판정은 모델 한계 |
| 5 | DVFS table 미연결 → m* 차이가 power에 미반영. DVFS fixture(CAM/INTCAM/INT) 추가 후 power Δ 보고 |
| 6 | UI/보고서(Architecture 검토 보고서 §⑧ SW margin Top5) 연동은 별도 작업 |
