# Architecture Exploration 검증 보고 (2026-09-25)

Branch `feat/arch-exploration` (base `feat/sw-timing-margin` 2b1e730).

## 자동 테스트

| 항목 | 결과 |
| --- | --- |
| `tests/unit/sim` (arch_exploration 11 포함) | 212 passed |
| `tests/unit/api` + reporting + alembic/db index (legacy 제외) | 191 passed |
| `tests/unit/test_*.py`, db, scripts (legacy 제외) | 398 passed |
| ruff / mypy (신규 sim·reporting 모듈을 mypy files에 추가) | clean |
| UI tsc / vitest / vite build | clean / 53 passed / OK |

## PostgreSQL 16 end-to-end (Alembic head → fixture ETL → API)

- Migration 0020 upgrade → downgrade → upgrade를 실행했고, `test_alembic_schema_drift` 로직(ORM ↔ DB)이 통과했다.
- `db_fixtures_Exynos2600_S26Plus` 전체 적재: scenario 13, variant 212.
- **run1**: Camera Recording 61 variant, 기본 축.
  - 소요 37.6 s. 조합 552,448 (eligible 465,408).
  - spec 만족 43, **추천 검증 43/43** (재시뮬레이션 |Δ| ≈ 0.00%).
- **run2**: 같은 scope에 lossy 금지 → 등록 시 run1 예측이 superseded.
  - uhd30-vdis: 674.28 → 866.96 mW. attribution 결과 Compression +192.68, 잔차 −0.004 mW.
- 대안 조합 등록: 사유 없음 → 422, 사유 있음 → `user:rank-2`.
  - 변경 원인은 INT L5→L4 → `IP DVFS 전압` +1.2 mW로 나타났다.
- 보고서 생성: HTML 273 KB, sha256 저장, stale = false.
- camera category 전체 (121 variant): 오류 0.
  - Preview 17개는 IP 전력 미모델로 spec 제외 (이전에는 0 mW로 잘못 추천됨 → 수정).

## 검증 중 발견·수정

| 문제 | 원인 | 수정 |
| --- | --- | --- |
| 추천 8건에서 analytic과 sim이 1–1.8% 불일치 | domain 안에 resolved voltage가 서로 다른 IP가 있을 때, 기준 level 옵션의 ΔP가 음수로 계산됨 | 기준 level ΔP = 0. 상향 시 member 전압은 max(V_new, V_ip) → 43/43 일치 |
| Preview variant가 0 mW로 추천됨 | IP `unit_power` 없음 | `require_power_model` 제약과 coverage 표시 추가 |
| 대안 목록에 추천과 같은 power가 중복 | 전력 미모델 IP(APV)의 level 상향이 0 mW | distinct 판정에 추천값 포함 |
| 보고서 box plot 축이 960 fps fail에 눌림 | 축을 공유 | spec 만족만 표시, 미달은 ②·⑧ 별도 표 |

## UI (Playwright, 1440/1000 px, 실제 API + PostgreSQL)

- 조합 탐색 / 예측 현황 / 보고서 / 새 탐색 폼: card overflow 0, page error 0.
- UI 흐름 확인: 새 탐색(Camera Recording APV 9 variant) → 전체 등록 9 → 보고서 생성 → 보고서 화면으로 이동.
