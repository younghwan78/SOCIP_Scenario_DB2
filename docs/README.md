# ScenarioDB Documentation

| Field | Value |
| --- | --- |
| Status | Current |
| Last verified | 2026-08-26 |
| Scope | `implementation/` current code and operational contract |
| Historical material | `../internal_docs/` |

이 디렉터리는 ScenarioDB의 현재 설계, 계약, 사용법, 운영 및 유지보수 절차의
정본이다. 날짜별 구현 계획, 조사 메모, worktree 실행 기록, 완료 체크리스트는
`internal_docs`에 둔다.

## Recommended reading paths

### 처음 구조를 파악할 때

1. [System Architecture](design/system-architecture.md)
2. [Ingestion and PostgreSQL SSOT](design/ingestion-and-ssot.md)
3. [Simulation and Evidence](design/simulation-and-evidence.md)
4. [Viewer and Projection](design/viewer-and-projection.md)
5. [Security and Write Lifecycle](design/security-and-write-lifecycle.md)

### API 또는 데이터 계약을 바꿀 때

- [API contract index](contracts/api/README.md)
- [Read API Contract](contracts/api/read-api-contract.md)
- [Write API Contract](contracts/api/write-api-contract.md)
- [Exploration API Contract](contracts/api/exploration-api-contract.md)
- [Measurement Evidence Contract](contracts/data/measurement-evidence-contract.md)
- [Metric Observation Contract](contracts/data/metric-observation-contract.md)
- [SoC Simulation Contract](contracts/simulation/soc-simulation-contract.md)

### 개발·운영·장애 대응을 할 때

- [Maintenance Guide](operations/maintenance-guide.md)
- [Testing Guide](operations/testing.md)
- [Ubuntu Deployment](operations/deployment-ubuntu.md)
- [Write API Runbook](operations/write-api-runbook.md)
- [Dashboard Regression Checklist](operations/dashboard-regression-checklist.md)
- [Troubleshooting](operations/troubleshooting.md)

### 데이터 준비와 사용 흐름을 수행할 때

- [DB Data Guide](guides/import/db-data-guide.md)
- [Legacy Fixture Import Guide](guides/import/legacy-data-import-guide.md)
- [CDGM Import Guide](guides/import/cdgm-import-guide-ko.md)
- [Exploration Fixture Guide](guides/exploration/exploration-fixture-guide-ko.md)
- [Measurement Import Guide](guides/measurement/measurement-import-guide-ko.md)
- [Projection Guide](guides/measurement/projection-guide-ko.md)
- [Prediction/Measurement Comparison Guide](guides/comparison/prediction-measurement-comparison-guide-ko.md)

## Directory policy

| Directory | Contains | Must not contain |
| --- | --- | --- |
| `design/` | Current architecture, boundaries, invariants | Worktree instructions, rollout checklist |
| `contracts/` | API/data behavior that code and tests must preserve | Proposals without implementation |
| `guides/` | Repeatable user workflows | Secrets, company identifiers, real raw data |
| `operations/` | Setup, maintenance, deployment, recovery | One-off debug transcripts |
| `reference/` | Stable naming and status-code reference | Week-based roadmap claims |

All repository examples and local validation use synthetic fixtures. Real company identities,
ACLs, URLs, credentials, traces, and measurement files belong only in an approved internal
environment and must not be committed.

Generated outputs are not documentation:

- process logs: `runtime_logs/`
- ETL, report, benchmark, compiled recipe, and QA artifacts: `output/`
- both locations are Git-ignored and disposable

## Document lifecycle

Current documents should declare `Status`, `Last verified`, scope, and the source code or tests
that pin the behavior. When a contract changes, update code, tests, and the linked document in
the same change. Superseded implementation material moves to `internal_docs`; it is not left in
`docs` with an ambiguous `Plan` or `Week N` title.
