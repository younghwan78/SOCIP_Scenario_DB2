# ScenarioDB API Contract Index

| Field | Value |
| --- | --- |
| Status | Current |
| Last verified | 2026-08-26 |
| Runtime source | `src/scenario_db/api/app.py`, `src/scenario_db/api/routers/` |
| Contract tests | `tests/unit/api/`, `tests/integration/` |

FastAPI의 `/openapi.json`, `/docs`는 실행 중인 build의 endpoint와 schema를 확인하는
가장 정확한 runtime reference다. 이 디렉터리의 문서는 endpoint를 단순 나열하는
대신 변경 시 지켜야 할 의미론과 호환성 경계를 설명한다.

## Router groups

| Group | Prefix or representative path | Responsibility |
| --- | --- | --- |
| Health | `/health/live`, `/health/ready` | Process and dependency readiness |
| Capability | `/api/v1/soc-platforms`, `/ip-catalogs`, `/sw-profiles` | SoC/HW/SW catalog reads |
| Definition | `/api/v1/projects`, `/scenarios`, `/variants` | Board, scenario, variant reads |
| Evidence | `/api/v1/evidence`, `/compare/*` | Evidence query and comparison |
| Decision | `/api/v1/issues`, `/waivers`, `/gate-rules`, `/reviews` | Review decision inputs |
| Runtime/View | `/api/v1/runtime/*`, `/scenarios/*/view` | Resolved graph and viewer projection |
| Explorer/Query | `/api/v1/explorer/*`, `/query/*` | Catalog/matrix exploration and architecture query |
| Exploration | `/api/v1/exploration/*` | Fixture-backed draft compile/run flows |
| Simulation | `/api/v1/simulation/*` | Readiness, run, result, artifact lifecycle |
| Write | `/api/v1/write/*` | Authenticated stage/validate/diff/apply workflow |
| Admin | `/api/v1/admin/*` | Disabled-by-default internal operations |

## Detailed contracts

- [Read API Contract](read-api-contract.md)
- [Write API Contract](write-api-contract.md)
- [Exploration API Contract](exploration-api-contract.md)
- [API Naming Conventions](../../reference/api-conventions.md)
- [API Status Codes](../../reference/api-status-codes.md)

Removing or renaming a response field, changing default filters, changing identity scope, or
weakening authentication is a contract change. Update the relevant document and tests in the
same commit.
