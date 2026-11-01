# Architecture Exploration → 예측 현황 → 변경 원인 → 검토 보고서

v3 제안(2026-09-24)의 구현 내용이다. Stage timing budget([timing-budget.md](timing-budget.md))을 기반으로 한다.

| 화면 (React) | 역할 | API |
| --- | --- | --- |
| `#/explore` 조합 탐색 | Scenario Type 단위로 전 조합을 평가하고, 최저 power 조합을 추천·등록 | `POST/GET /api/v1/arch/exploration/runs` |
| `#/predictions` 예측 현황 | variant별 current 예측, 직전 대비 Δ, 변경 원인 waterfall, 등록 이력 | `GET /arch/predictions/board`, `/history`, `/compare` |
| `#/reports` 검토 보고서 | DB에 저장된 보고서 열람, 게시, 재생성, HTML export | `POST/GET /arch/reports`, `/{id}/html`, `/{id}/stale` |

## 1. 조합 탐색 (`sim/arch_exploration.py`)

| 축 | 계산 방식 | 비고 |
| --- | --- | --- |
| SW 통계 (mean/max) × 차기 SW 증가 (×1.0~) | timeline sim (`analyze_timing_budget`) | slice당 ~30 ms |
| DVFS headroom (domain별 resolved level ~ +k level) | analytic: IP power × (V/V0)² | scenario마다 CAM level이 다를 수 있음 |
| Buffer compression (OFF / lossy·lossless) | analytic: 실제 adapter를 `buffer_overrides`로 다시 실행해 port별 ΔBW·ΔP 산출 | buffer 간 port가 독립이므로 합산 가능 (검증: 개별 합 = 동시 적용) |

- Ratio 우선순위: 요청의 `ratio_overrides` → SoC `compression_modes` catalog (ratio < 1) → assumed(LOSSY 0.5).
  - lossless는 catalog ratio가 1.0이면 탐색하지 않는다 (절감 없음).
- IP 지원: 양 끝 IP catalog의 `supported_features.compression`을 보고 `catalog` / `unknown` / `unsupported`로 표시한다. `unsupported`는 기본 제외.
- 탐색 대상 buffer는 절감 상위 `max_buffers`(기본 8)개다. 조합 수 = SW slice × 2^buffer × Π(k+1)^domain.
  - variant당 상한은 200k이며 요청에서 상향할 수 없다. run 전체는 최대 2M 조합이고 한 project만 포함한다.
  - 실제 각 SW slice의 DVFS 조합 수를 합산한다. 제한으로 처리하지 못한 variant는 errors에 명시된다.
- **Eligible 조건**:
  - verdict ≠ fail
  - 간격 ±0.1% 만족
  - IP 전력 모델 존재 (hw_mw > 0)
  - (선택) lossy 허용, power/BW budget 이하
- **추천**: 목적 통계(기본 max)·목적 증가율(기본 ×1.0)의 eligible 조합 중 최저 total power.
  - 1% 이내 동률이면 BW 낮은 쪽 → compression buffer 수 적은 쪽 → level 상향 수 적은 쪽.
- **검증**: 추천 조합을 `buffer_overrides` + `dvfs_overrides`로 다시 시뮬레이션해 analytic 값과 비교한다.
  - `|Δ| < 0.5%`이고 fail이 아니면 `verified.ok`. 검증 실패는 spec OK로 표시하거나 예측으로 등록할 수 없다.
- **SW timing margin**: 판정 기준(`throughput_model`)과 같은 규칙으로 계산한다 (engine rev 15). NRT와 Post-NRT 중 최솟값이다.
  - `stage`: (P − SW(runtime+latency) − IP overhead − HW@set clock) / P — stage 전체가 1 frame 안에 끝나야 한다.
  - `pipelined`: (P − max(최장 SW task, 같은 CPU에서 순차 실행되는 SW 합)) / P — task마다 thread이고 frame N+1이 N의 후단과 겹친다.
    stage chain(SW + HW)이 P를 넘으면 그만큼 frame이 동시에 처리된다(`in_flight`, latency만 증가). `chain_ms` · `chain_margin_pct`로 따로 기록한다.
  - margin 행은 `basis`(stage / pipelined)를 남긴다. rev 14 이전 예측에는 없고 stage 식으로 계산된 값이다.
  - 권고 규칙: spec 미달, 단일 task > 50%(stage), latency > 30%(stage), 동시 frame(pipelined), clock_up, max–mean 편차, SW 증가 허용치.

- **Power 구성** (engine rev 3): CPU(SW) + CPU BW(SW task DMA, 예: mpeg_writer/storage_write) + IP core + IP BW.
  - 분포(`distribution`)와 case에 `bw_ip_mw`/`bw_cpu_mw`/`bw_ip_mbs`/`bw_cpu_mbs`를 추가했습니다. compression Δ도 port 소유 node 기준으로 IP/CPU로 나눕니다.
  - rev 1 run·예측은 BW 전체를 IP BW로 표시하고, 변경 원인에서는 합산 "BW traffic" 1개 항목으로만 비교합니다.
- **UI 표현**: range 카드(box = 조합 분포, ◆ 추천, ○ baseline)와 구성 카드(추천 조합의 CPU/CPU BW/IP/IP BW 절대값 막대)를 분리했습니다.

## 2. 예측 등록 (current / superseded)

- `POST /arch/predictions/promote {run_id, scenario_id?, variant_ids?, case_key?, reason?}`
  - 기본값: run의 spec 만족 variant 전체를 **최저 power 조합**(`auto:min-power`)으로 등록한다.
  - 대안 조합(`case_key`)은 variant 1개에만 지정할 수 있고 사유가 필수다 (`user:rank-N`).
- 기존 current는 `superseded`로 바뀌고 `supersedes_ref`로 연결된다. variant당 current는 1개다 (partial unique index).
- variant ID는 scenario 내에서만 고유하다. 같은 이름이 여러 scenario에 있으면 개별 등록에 `scenario_id`가 필요하다. 전체 등록은 모든 scenario/variant 쌍을 보존한다.
- 등록은 variant 행을 잠가 직렬화하며, 동시에 처음 등록하더라도 current 하나와 superseded 이력 체인을 유지한다.
- `metrics`에 frozen payload를 저장한다: IP별 power·전압·activity, SW task별 CPU, buffer별 raw BW와 압축 Δ, DVFS level, 분포.

## 3. 변경 원인 (`sim/power_attribution.py`)

| 성분 | 분해 |
| --- | --- |
| CPU (SW) | task별 Δ (추가/제거/runtime) |
| HW (IP core) | P = activity × (V/710)². 2-factor LMDI로 **IP workload**(size/fps/mode/cores)와 **IP DVFS 전압**을 분리 |
| BW | **DMA traffic**(압축 전: size/fps/topology) + buffer별 **Compression** Δ |

항목 합 = 총 Δ이고 잔차는 반올림 수준(< 0.01 mW)이다. 입력 변경(fps, SW 통계·증가, compression set, DVFS level, run)도 함께 표시한다.

분해는 같은 계산 모델을 전제로 한다. 두 예측의 model lineage(power model · version · BW model · 계수 · clock 기준)나
engine이 다르면 Δ의 일부가 모델 차이이므로, 예측 현황 비교(`lineage_warning`)와 보고서 "변경 이력"은 그 행을
"모델 · engine 변경 포함"으로 표시하고 분해를 참고로만 보여준다.

## 4. Architecture 검토 보고서 (`reporting/arch_report.py`)

- `POST /arch/reports {run_id}`: 그 run에서 등록된 current 예측으로 snapshot(JSON)을 고정하고, self-contained HTML(inline SVG)을 생성해 `arch_reports`에 저장한다.
- `POST /arch/reports {project_ref}`: 과제 보고서. 과제의 current 예측 전체(여러 run)를 한 snapshot으로 묶고 risk register를 갱신한다.
  직전 과제 보고서와의 비교(`previous`)를 함께 고정한다.
  - 행마다 계산한 engine(`engine_rev`)과 model lineage를 고정한다. 생성 시점 engine(`overview.engine_current`)과 다른 행,
    서로 다른 lineage가 섞인 경우는 "게시 전 확인 필요"(`stale_engine` · `mixed_lineage`, 게시 시 확인 체크 필요)로,
    power params 미지정(코드 기본 계수)은 경고(`default_params`)로 표시한다.
  - `/stale`은 현재 예측이 snapshot과 다르면(`changed`, 재생성으로 해소) `stale`로 알려준다. 이전 engine으로 계산된 행은
    `old_engine`으로 따로 알려준다 — 재생성으로는 해소되지 않고 재탐색 · 재등록이 필요하다.
  - 실제 등록한 비압축 조합과 검증 여부를 보존한다. 추천 조합의 설정/검증 결과로 대체하지 않는다.
- 구성 (과제 보고서, `reporting/review_sections.py`):
  - Tier 0 — 요약: 근거 등급, 과제 조건, KPI scenario 표(SW 여유는 탐색 목적 통계 기준 — Timing Budget 화면 기본 mean과 다를 수 있음),
    게시 전 확인 항목, 핵심 메시지, Top risk, 결정 요청.
  - Tier 1 — 결론 · Risk register · 이전 보고서 대비 (Power 변화마다 계산 모델 변경 여부 표시).
  - Tier 2 — 성능 · Timing / Power 구성 / Lever · 발열 / CPU · SW / 예측 ↔ 실측.
    - CPU · SW: CPU what-if "검토서에 포함" snapshot. 허용치 = min(비용 ≥ 5 mW 또는 5%인 첫 OPP 상향 직전 배율,
      Timing Budget 여유(RT chain 포함) 소진 배율), 판정 기준 = review_policy `sw_growth_budget`. 범위 안 OPP 상향을 모두 나열하고,
      이전 계산 방식으로 기록된 snapshot은 "이전 계산"으로 표시한다.
  - Tier 3 — 분류별 의견 (`reporting/arch_opinions.py`), 검토 범위 · 모델(모델 한계: power model · version, BW model, CPU flat/profile 비중),
    dossier, 요약 표, SW margin(판정 기준별 정의), 변경 이력(모델 · engine 변경 행 분리), 부록.
  - 분류: 30 fps(해상도 × EIS on/off × HEVC/APV) · 60 fps(FHD/UHD) · 고속(≥100 fps) · Heavy(Pro/Portrait/Dual·PIP·RCV/Triple).
    분류 입력은 run에 저장된 resolved `design_conditions`와 `severity`다.

## 5. DB

Alembic `0020_arch_exploration`: `arch_exploration_runs`, `predictions`, `arch_reports`.

## 6. 한계

- BW 전력의 MIF DVFS 반영은 BW model에 따른다: `builtin` · 계수 모델은 미반영, `mif-linear`는 MIF level · read/write 분리 반영.
- 탐색 예측의 CPU 전력은 기본 `cpu_model = flat`(fps 비례 항)이다. task 배치 · cluster OPP는 `profile`(실측 CPU profile)이거나
  CPU what-if 결과에서만 반영된다. 보고서 모델 한계에 flat / profile 건수가 표시된다.
- Compression은 BW만 감소시킨다 (codec 전력과 화질은 미반영).
- sample DVFS는 CAM/INTCAM/INT/APV가 synthetic이다.
- 고 fps batch는 모델링하지 않았다.
- Preview scenario 일부는 IP `unit_power`가 없어 spec 판정에서 제외된다.
