# Timing Budget 검증 보고 (2026-09-25)

Branch `feat/sw-timing-margin`. v1 `sw_margin`(scalar margin)을 stage slot 모델로 대체.

## 단위/통합 테스트

| 항목 | 결과 |
| --- | --- |
| `tests/unit/sim` (timing_budget 15 포함) | 201 passed |
| `tests/unit/api` (timing_budget 4 포함, legacy import 제외) | 165 passed |
| ruff / mypy (timing_budget 모듈, api) | clean |
| UI `tsc` / `vitest` / `vite build` | clean / 48 passed / OK |

주요 test 항목:
- stage 분류와 예산 (uhd30-vdis NRT SW 11.1 ms, EIS 6.0 ms)
- RT 25% rule, mean < max, EIS toggle, SW 증가에 대한 단조성, `ip_overhead`
- PIP 병렬 chain, MFC dual, DVFS level, power/BW split
- fhd240 fail, what-if, 입력 read-only, 잘못된 옵션 reject

## Fixture fleet (uc-camera-recording, 61 variants, max)

| DVFS | ok | clock_up | fail |
| --- | ---: | ---: | ---: |
| sample v0 | 26 | 17 | 18 |
| 없음 | 0 | 54 | 7 |

- fail은 두 종류다.
  - ≥120 fps: NRT SW 11.1 ms > P라서 예산이 없다 (batch 미모델링).
  - dual/triple/front RT: synthetic CAM max 1066 MHz를 초과한다.
- uhd30-vdis, DVFS 없음:
  - NRT HW 예산 22.23 ms → MTNR 93.7 → 110.6 MHz (×1.18).
  - GDC 예산 27.33 ms.
  - 간격 33.333 ms로 OK.
  - latency preview 51 ms / video 59 ms.
  - Power 867 mW (CPU 311 / HW 127 / BW 429), BW 5.37 GB/s (SW 30 MB/s).
- uhd30-vdis, sample DVFS: rule clock과 budget clock이 같은 level(L4/L5)에 들어가 verdict ok.

## UI 검증 (Playwright, Chromium, 1440/900 px, fixture harness)

- Variant 상세: 6개 card 모두 `scrollWidth == clientWidth`, card 밖으로 나간 SVG 0.
- Fleet: 순위 차트는 행 기반이라 겹침이 없다. 표는 header 정렬, 가로 스크롤은 table 내부.
- 수정한 내용:
  - KPI 6개가 5+1로 줄바꿈되던 문제 수정 (minmax 160 px).
  - Power tile note의 말줄임을 줄바꿈으로 변경.
  - Gantt NRT HW lane이 frame별 첫 IP(vps_od)만 표시하던 문제 → 병렬 IP 구간의 union으로 표시.
  - Fleet 표 `Post SW` 열 폭 조정.

## 남은 항목

- 사내 DVFS table, SW task latency, IP overhead 입력
- 고 fps batch 모델
- 조합 탐색 / current 승격 / architecture review report (v3 제안)
