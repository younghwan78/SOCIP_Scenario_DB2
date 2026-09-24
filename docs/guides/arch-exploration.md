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
- **SW timing margin** = (P − SW(runtime+latency) − IP overhead − HW@set clock) / P. NRT와 Post-NRT 중 최솟값이다.
  - 권고 규칙: spec 미달, 단일 task > 50%, latency > 30%, clock_up, max–mean 편차, SW 증가 허용치.

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

## 4. Architecture 검토 보고서 (`reporting/arch_report.py`)

- `POST /arch/reports {run_id}`: 그 run에서 등록된 current 예측으로 snapshot(JSON)을 고정하고, self-contained HTML(inline SVG)을 생성해 `arch_reports`에 저장한다.
  - `/stale`은 현재 예측이 snapshot과 다르면 알려준다. 같은 run에서 재등록한 경우 보고서를 재생성한다. 다른 run의 예측으로 변경한 경우 해당 새 run에서 보고서를 생성한다.
  - 실제 등록한 비압축 조합과 검증 여부를 보존한다. 추천 조합의 설정/검증 결과로 대체하지 않는다.
- 구성:
  1. 개요
  2. spec 만족 수와 미달 원인
  3. scenario 요약
  4. DVFS domain level (scenario별) + IP 상세
  5. Power·BW box plot
  6. CPU/HW/BW 분리
  7. Compression 절감
  8. SW margin Top 5 + 권고, spec 미달 목록
  9. 변경 이력 (attribution)
  10. 부록

## 5. DB

Alembic `0020_arch_exploration`: `arch_exploration_runs`, `predictions`, `arch_reports`.

## 6. 한계

- MIF DVFS는 BW 전력에 반영되지 않는다.
- CPU 전력은 단일 cluster 가정이다.
- Compression은 BW만 감소시킨다 (codec 전력과 화질은 미반영).
- sample DVFS는 CAM/INTCAM/INT/APV가 synthetic이다.
- 고 fps batch는 모델링하지 않았다.
- Preview scenario 일부는 IP `unit_power`가 없어 spec 판정에서 제외된다.
