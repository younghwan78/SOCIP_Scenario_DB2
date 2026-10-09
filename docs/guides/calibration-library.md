# 예측 ↔ 실측 · Library · Home

1차 범위 page 3종과 sidebar 정리. Streamlit은 `설정 › 기존 도구`로만 연결한다.

## 예측 ↔ 실측 (`#/calibration`)

API (read-only, 인증 불필요)

| Endpoint | 내용 |
|---|---|
| `GET /api/v1/calibration/measurements?scenario_id=` | measurement evidence 목록: 실측 total (mean/std/p95/CI), 등록(current) 예측 Δ%, 같은 variant의 최신 simulation evidence Δ% |
| `GET /api/v1/calibration/coverage?scenario_id=` | variant별 simulation 수 · 실제/합성 measurement 수 · current 예측 (Scenario 표의 `예측` `실측` 열) |
| `GET /api/v1/calibration/measurements/{id}` | rail 분류 split, 예측별 CPU/IP/BW 비교 행, rail 표, SW task 실측 |

Rail → 구분 (`comparison/calibration.py`)

| 우선순위 | 근거 |
|---|---|
| 1 | project의 최신 SimConfigProfile `rail_domain_map` (CPU→cpu, MIF/MEM/DRAM→bw, GPU/NPU/SRAM/ICPU 등→other, 그 외→ip) |
| 2 | `vdd_power[rail].domain` hint |
| 3 | 이름 규칙 (순서: 기타 `G3D·GPU·SRAM·ICPU·NPU·AUD·MODEM` → cpu `CPUCL·DSU·VDD_CPU` → bw `MIF·VDD2H/2L·VDDQ·MEM·DRAM` → ip `CAM·INT·MFC·DPU·ISP·MM`) |

- 예측 BW power는 모델상 MIF·DRAM rail로 귀속 (MIF DVFS 미반영) → BW 오차는 이 가정의 오차를 포함.
- `기타` rail은 scenario power model 밖 → 예측 없음(미모델). total Δ와 split Δ를 따로 읽을 것.
- 예측값 0 mW(예: CPU를 모델링하지 않은 sim)는 −100 %가 아니라 `미모델`로 표시.
- 표시 기준: |Δ| ≤10 % 녹색, ≤25 % 주황, 그 외 빨강. 표준편차는 rail별 std의 RSS.
- Simulation 열: `power_breakdown`이 있는 evidence만 split 비교, 날짜 suffix로 구분 (`Sim MM-DD`). KPI tile·목록은 최신 sim.
- 최신 simulation은 `measured_at` 기준이며 시각이 없는 evidence는 뒤로 둔다. project가 없는 실측은 소유 scenario의 project를 사용하며 다른 project의 rail map은 사용하지 않는다.

### 계수 보정 (S5)

`예측 ↔ 실측` 하단 **계수 보정** 카드. 기존 params는 바꾸지 않고 새 draft 버전을 만든다.

| 단계 | API | 내용 |
|---|---|---|
| 보정 계산 | `POST /calibration/power-fit` | 과제의 각 측정을 같은 조건(Timing Budget · SW 통계 · 측정 SW runtime 입력 · 기준 params)으로 예측 → rail 구분(CPU · IP · BW)별 k = Σp·m / Σp² (원점 통과 최소제곱, 0.2–5 제한), RMSE · MAPE 전후 · R². `recommended` = n ≥ 3 · R² ≥ 0.5 · MAPE 개선 |
| 새 params 버전 | `POST /calibration/power-params` | 체크한 k만 적용: CPU = EM table·DSU·leakage 계수 × k, BW = mif-linear 계수(e_rd · e_wr · MIF base) / mw_per_gbps × k, IP = `calibration.ip_power_scale["*"]` (engine이 IP power에 곱함, key = node · hw · ip_ref · DVFS domain · `*`). 버전 = SoC 최대+1, status draft, `calibration.fit`·`source_evidence`에 lineage. YAML을 함께 돌려주며 DB row는 작업본 — 유지하려면 authoring / db YAML에 커밋 |
| 검증 | (보정 계산 재실행) | 새 params로 같은 측정을 다시 계산해 k ≈ 1이면 반영 확인 |
| 사용 | Timing Budget `power params` (URL `pp`) · 예측 현황 `재계산…` | 재계산 = `POST /arch/predictions/{id}/recompute?power_params_ref=` — 등록 조건 그대로(Timing Budget 조건 또는 조합 탐색 spec) 다시 계산해 새 버전 등록, 사람이 고른 조합(user:…)은 건너뜀 |

- 합성 측정은 기본 제외(포함 시 경고). 단일 배율로 설명되지 않는 구분(R² 낮음, MAPE 악화)은 비권장으로 표시 — OPP·SW 부하·rail 귀속 등 모델 구조 확인 대상.
- `ip_power_scale`이 비어 있으면(기존 params 전부) engine 결과와 params hash는 이전과 같다.

### 합성(SYNTHETIC) 측정 fixture

- `provenance.collection_method: synthetic_fixture` 또는 `device_id: SYNTHETIC`이면 API가 `synthetic: true`를 돌려준다.
- 목록에 `합성` badge, 상단 filter `합성 포함 | 실제 측정만` (param `real=1`), 상세에 경고 배너와 source(`derived_from`).
- 생성: `scripts/generate_rear_recording_evidence.py` (rear Camera Recording gap fill, fixture README 참고).

## Library (`#/library`)

| 탭 | Source | 비고 |
|---|---|---|
| IP | `/ip-catalogs` | HW·VDD·DVFS group·mode 수·compression·`sim.source` (assumed/borrowed 등) |
| DVFS | `/soc-dvfs-tables` | domain별 level × ASV 전압, source note (SAMPLE/SYNTHETIC 경고) |
| Compression | `/soc-platforms` `compression_modes` | comp_ratio, compressor |
| Sensor | `/sensors/catalogs`, `/sensors/timing-profiles` | Streamlit Sensor Catalog 대체 |
| SW timing | `GET /api/v1/library/sw-timing` | variant `node_configs.sw_timing`의 min/mean/max/latency 범위 + 출처, 아래에 measurement `sw_task_timing` |

Driver model은 `/driver-models`가 scenario/variant 필수라 이번 범위에서 제외 (Pipeline 상세에서 열람).

## Home (`#/`, brand 클릭)

- Canvas 2D perspective fly-through (WebGL 없음). stage 이름은 역할 기반(`CAPTURE`, `RAW FRONT`, `COLOR`, …), IP 이름은 HUD의 "IP 매핑 예"로만.
- Camera / Video playback / Display 전환. `prefers-reduced-motion`이면 정지, tab hidden이면 rAF 중단.
- SSO 버튼은 placeholder (연동 예정). 현황 카드: scenario·variant, current 예측, 최근 run·보고서, 예측↔실측 최대 |Δ|.

## Sidebar

- 그룹: 탐색 (Scenario·Pipeline·Compare) · 예측 (Timing Budget·예측 현황·예측 ↔ 실측) · Architecture (조합 탐색·검토 보고서) · Library. 하단: 설정 · 기존 도구, API 상태, 접기.
- 색·크기는 `ui/src/styles.css`의 `--sd-*` token (폭 232 / rail 64, row 36px). 사내 design system 적용 시 token만 교체.

## Streamlit 은퇴 매핑

| Streamlit | React | 상태 |
|---|---|---|
| DB Explorer · Pipeline Viewer · Variant Compare | Scenario · Pipeline · Compare | 대체 완료 |
| Evidence Dashboard | 예측 ↔ 실측 | 대체 |
| Sensor Catalog | Library › Sensor | 대체 |
| Camera Profiling | 예측 ↔ 실측 (열람) | 업로드는 2차 DB Import |
| Driver Models | — | Library 확장 예정 |
| Exploration Workbench · Import Workbench | 조합 탐색 / 2차 DB Import | recipe/sweep compile·import는 2차 |
| Architecture Query | — | 2차 Ask (LLM query) |

## 검증

- `pytest tests/unit/test_calibration.py` (rail 규칙, 우선순위, split, 0 mW=미모델, route)
- `ui/tests/home-library.test.ts` (generic stage 이름, domain 매핑, 오차 등급, IP 요약, route)
- fixture 실측 1건 (`uc-camera-recording` uhd30-vdis): total 675.2 ±7.1 mW, 등록 예측 674.3 (−0.1 %), split CPU +17 % / IP −37 % / BW +58 % → total은 맞지만 구성비는 보정 필요.
