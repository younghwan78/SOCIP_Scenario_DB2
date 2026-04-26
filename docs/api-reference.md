# ScenarioDB API Reference — Week 1 Public MVP

## 파일 구조 (최종)

```
src/scenario_db/
├── api/
│   ├── app.py              # lifespan, middleware, router 마운트
│   ├── deps.py             # get_db, get_rule_cache
│   ├── cache.py            # RuleCache DTO + match_issues_for_variant
│   ├── pagination.py       # apply_sort, validate_sort_column
│   ├── validators.py       # feature_flag / category whitelist
│   ├── exceptions.py       # 404/409/422 handler
│   ├── schemas/
│   │   ├── common.py       # PagedResponse, ErrorResponse
│   │   ├── capability.py
│   │   ├── definition.py
│   │   ├── evidence.py
│   │   └── decision.py
│   └── routers/
│       ├── capability.py   # SoC / IP / SW
│       ├── definition.py   # Project / Scenario / Variant / matched-issues
│       ├── evidence.py     # Evidence / compare
│       ├── decision.py     # Issue / Waiver / GateRule / Review
│       └── utility.py      # /health/live + /health/ready
├── db/
│   ├── models/             # 15개 ORM 모델
│   ├── repositories/       # capability / definition / evidence / decision
│   ├── session.py
│   └── jsonb_ops.py + sql_matcher.py
├── matcher/                # context.py + runner.py (AST evaluator)
└── etl/                    # loader + mappers
```

---

## 구현된 엔드포인트 목록

| Method | Path | 파라미터 | 설명 |
|--------|------|---------|------|
| GET | `/health/live` | — | Liveness probe (무조건 200) |
| GET | `/health/ready` | — | Readiness probe (DB+cache, 503 if not ready) |
| GET | `/api/v1/soc-platforms` | limit, offset, sort_by, sort_dir | SoC 플랫폼 목록 |
| GET | `/api/v1/soc-platforms/{id}` | — | SoC 플랫폼 상세 |
| GET | `/api/v1/ip-catalogs` | category, limit, offset, sort_by, sort_dir | IP 카탈로그 목록 |
| GET | `/api/v1/ip-catalogs/{id}` | — | IP 카탈로그 상세 |
| GET | `/api/v1/sw-profiles` | feature_flag, limit, offset, sort_by, sort_dir | SW 프로필 목록 |
| GET | `/api/v1/sw-profiles/{id}` | — | SW 프로필 상세 |
| GET | `/api/v1/sw-components` | category, limit, offset, sort_by, sort_dir | SW 컴포넌트 목록 |
| GET | `/api/v1/projects` | limit, offset, sort_by, sort_dir | 프로젝트 목록 |
| GET | `/api/v1/projects/{id}` | — | 프로젝트 상세 |
| GET | `/api/v1/scenarios` | limit, offset, sort_by, sort_dir | 시나리오 목록 |
| GET | `/api/v1/scenarios/{id}` | — | 시나리오 상세 |
| GET | `/api/v1/scenarios/{sid}/variants` | limit, offset, sort_by, sort_dir | Variant 목록 |
| GET | `/api/v1/scenarios/{sid}/variants/{vid}` | — | Variant 상세 |
| GET | `/api/v1/scenarios/{sid}/variants/{vid}/matched-issues` | — | Matched Issues + eval_time_ms |
| GET | `/api/v1/variants` | project, severity, tag, limit, offset, sort_by, sort_dir | 전체 Variant |
| GET | `/api/v1/evidence/summary` | groupby | Evidence 집계 |
| GET | `/api/v1/evidence` | scenario_ref, variant_ref, sw_version, feasibility, limit, offset, sort_by, sort_dir | Evidence 목록 |
| GET | `/api/v1/evidence/{id}` | — | Evidence 상세 |
| GET | `/api/v1/compare/evidence` | variant, sw1, sw2 | SW 버전 KPI 비교 |
| GET | `/api/v1/compare/variants` | ref1, ref2 | Variant 비교 |
| GET | `/api/v1/issues` | limit, offset, sort_by\*, sort_dir\* | Issue 목록 (캐시 우선) |
| GET | `/api/v1/issues/{id}` | — | Issue 상세 (캐시 우선) |
| GET | `/api/v1/waivers` | expiring_within_days, limit, offset, sort_by, sort_dir | Waiver 목록 |
| GET | `/api/v1/waivers/{id}` | — | Waiver 상세 |
| GET | `/api/v1/gate-rules` | limit, offset, sort_by\*, sort_dir\* | GateRule 목록 (캐시 우선) |
| GET | `/api/v1/reviews` | limit, offset, sort_by, sort_dir | Review 목록 |
| GET | `/api/v1/reviews/{id}` | — | Review 상세 |

\* Issues/GateRules는 캐시 적재 시 sort 미적용 (in-memory), DB fallback 시에만 sort 동작.

총 **29개 GET 엔드포인트** — admin/write/stub 완전 제거.

---

## Pagination 공통 파라미터

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `limit` | 50 | 최대 1000 |
| `offset` | 0 | 0-based |
| `sort_by` | 없음 (id 기본) | 모델 컬럼명 (whitelist 검증, 400 if invalid) |
| `sort_dir` | asc | `asc` 또는 `desc` (대소문자 구분, 400 if invalid) |

응답 구조:
```json
{
  "items": [...],
  "total": 42,
  "limit": 50,
  "offset": 0,
  "has_next": false
}
```

---

## 실행 방법

```bash
# 개발 서버 (PostgreSQL 필요)
DATABASE_URL="postgresql+psycopg2://user:pass@localhost/scenariodb" \
uv run uvicorn scenario_db.api.app:app --reload --port 8000

# 테스트 — unit only (Docker 불필요)
uv run pytest tests/unit/ -q

# 테스트 — integration (Docker 필요)
uv run pytest tests/integration/ -v

# 전체
uv run pytest tests/unit/ tests/integration/
```

---

## 테스트 목록

| 파일 | 유형 | 테스트 수 | 주요 검증 |
|------|------|----------|----------|
| `tests/unit/api/test_smoke.py` | unit | 40 | 전체 엔드포인트 2xx/4xx, health 분리, sort params |
| `tests/unit/api/test_pagination.py` | unit | 17 | validate_sort_column, apply_sort 에러, PagedResponse |
| `tests/unit/matcher/test_runner.py` | unit | 25+ | AST evaluator 12 operators |
| `tests/unit/matcher/test_context.py` | unit | 14 | MatcherContext 경로 파싱 |
| `tests/unit/test_*_models.py` | unit | 4파일 | Pydantic 모델 라운드트립 |
| `tests/integration/test_matched_issues.py` | integration | 7 | /scenarios/{sid}/variants/{vid}/matched-issues E2E |
| `tests/integration/test_api_capability.py` | integration | 13 | JSONB feature_flag, /ip-catalogs |
| `tests/integration/test_api_definition.py` | integration | 12 | 실 Variant/Scenario 조회 |
| `tests/integration/test_api_evidence.py` | integration | 10 | Evidence 필터, groupby, compare |
| `tests/integration/test_api_decision.py` | integration | 8 | 캐시 우선 서빙 |
| `tests/integration/test_cache.py` | integration | 5 | RuleCache 로드, match |
| `tests/integration/test_jsonb_queries.py` | integration | 16 | JSONB 연산자, GIN 인덱스 |
| `tests/integration/test_phase_c_jsonb.py` | integration | 32 | SQL 하이브리드 매칭, cross-match |

총 **230 unit + 108 integration = 338개 테스트**

---

## 대표 curl 예시

```bash
# 1. Liveness
curl http://localhost:8000/health/live

# 2. Readiness (DB + cache 상태)
curl http://localhost:8000/health/ready

# 3. SoC 플랫폼 목록 (id 내림차순)
curl "http://localhost:8000/api/v1/soc-platforms?sort_by=id&sort_dir=desc"

# 4. IP 카탈로그 — ISP 카테고리 필터
curl "http://localhost:8000/api/v1/ip-catalogs?category=ISP&limit=10"

# 5. SW 프로필 — JSONB feature_flag 필터
curl "http://localhost:8000/api/v1/sw-profiles?feature_flag=LLC_per_ip_partition:disabled"

# 6. Scenario 내 Variant 목록 (pagination)
curl "http://localhost:8000/api/v1/scenarios/uc-camera-recording/variants?limit=20&offset=0"

# 7. Matched Issues — 핵심 엔드포인트
curl "http://localhost:8000/api/v1/scenarios/uc-camera-recording/variants/UHD60-HDR10-H265/matched-issues"

# 8. Evidence — sw_version 필터
curl "http://localhost:8000/api/v1/evidence?sw_version=sw-vendor-v1.2.3"

# 9. Evidence 집계 (SW 버전별 count)
curl "http://localhost:8000/api/v1/evidence/summary?groupby=sw_version_hint"

# 10. Issue 상세 (캐시 우선 서빙)
curl "http://localhost:8000/api/v1/issues/iss-LLC-thrashing-0221"
```

---

## Deferred (Phase C/D 이월)

| 항목 | 이유 |
|------|------|
| `POST /admin/cache/refresh` | internal 운영 도구 — VPN 뒤에서만 노출 예정 |
| `POST /variants/generate-yaml` | Week 4 YAML export |
| `POST /scenarios/{sid}/variants` | Write API Phase |
| `POST /scenarios/{sid}/variants/{vid}/review` | Gate automation Phase C |
| `POST /admin/etl/trigger` | ETL 자동화 Phase D |
| services/ 계층 | Phase C 집계 로직 추가 시 도입 |
| Prometheus metrics | Phase C observability |
| Rate limiting | 인증 API 도입 시 |
| EXPLAIN ANALYZE 자동화 | 별도 `scripts/bench_jsonb.py`로 분리 예정 |
| Issues/GateRules 캐시 경로 sort | in-memory 정렬 추가 (성능 영향 미미, Phase C에서 결정) |
