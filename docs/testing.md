# Testing Guide — ScenarioDB

## 테스트 계층

```
tests/
├── unit/           Pure Python — DB 없음, Docker 불필요
│   ├── test_capability_models.py   Pydantic v2 모델 검증 (HW Capability)
│   ├── test_definition_models.py   Pydantic v2 모델 검증 (Definition)
│   ├── test_evidence_models.py     Pydantic v2 모델 검증 (Evidence)
│   ├── test_decision_models.py     Pydantic v2 모델 검증 (Decision)
│   ├── matcher/
│   │   ├── test_runner.py          Matcher AST Evaluator (31 tests)
│   │   └── test_context.py         MatcherContext 경로 해석 (15 tests)
│   └── api/
│       └── test_smoke.py           FastAPI 라우팅 wiring (MagicMock, 39 tests)
│
└── integration/    실 PostgreSQL — Docker 필요
    ├── conftest.py                 session-scope fixtures (container/engine/cache/client)
    ├── test_cache.py               RuleCache 실 DB 로드 + match_issues_for_variant
    ├── test_matched_issues.py      /variants/*/matched-issues E2E
    ├── test_api_capability.py      Capability 레이어 API
    ├── test_api_definition.py      Definition 레이어 API
    ├── test_api_evidence.py        Evidence 레이어 API
    ├── test_api_decision.py        Decision 레이어 API (RuleCache 우선 서빙)
    └── test_jsonb_queries.py       JSONB 연산자/GIN 인덱스/Generated Column 전용
```

| 계층 | 테스트 수 | 실행 시간 | Docker |
|------|-----------|-----------|--------|
| unit | 209 | ~1s | 불필요 |
| integration | 76 | ~3s | 필요 |

---

## 로컬 실행

### Unit만 (기본)

```bash
uv run pytest tests/unit/
# 또는 pyproject.toml testpaths = ["tests/unit"] 이므로 그냥:
uv run pytest
```

### Integration만 (Docker 필요)

```bash
# Docker Desktop이 실행 중이어야 함
uv run pytest tests/integration/ -v
```

### 전체

```bash
uv run pytest tests/unit/ tests/integration/
```

### JSONB 전용

```bash
uv run pytest tests/integration/test_jsonb_queries.py -v
```

---

## Docker 필수 여부

| 명령 | Docker |
|------|--------|
| `uv run pytest` | ❌ 불필요 |
| `uv run pytest tests/unit/` | ❌ 불필요 |
| `uv run pytest tests/integration/` | ✅ 필요 |

통합 테스트는 `testcontainers` 라이브러리가 `postgres:16-alpine` 컨테이너를 자동 기동·종료합니다.
컨테이너는 session scope — 테스트 세션당 1회만 기동되므로 재시작 오버헤드 없음.

---

## 통합 테스트 fixture 흐름

```
pg (PostgresContainer) ← session scope
  └─ engine (Alembic migration + ETL 로딩)
       ├─ rule_cache (RuleCache.load)
       └─ api_client (TestClient + dependency_overrides)
```

1. `pg`: `postgres:16-alpine` 컨테이너 기동
2. `engine`: `alembic upgrade head` → `demo/fixtures/` 전체 ETL 로딩 (20개 YAML)
3. `rule_cache`: Issue + GateRule 메모리 캐시 적재
4. `api_client`: FastAPI lifespan noop + `get_db` / `get_rule_cache` 의존성 주입

---

## CI 동작 방식

현재 CI 미설정 상태. 아래는 권장 구성입니다.

### GitHub Actions (Docker-in-Docker 지원)

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]

jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen
      - run: uv run pytest tests/unit/ -q

  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen
      - run: uv run pytest tests/integration/ -v
    # testcontainers가 Docker socket을 사용 → ubuntu-latest runner에서 동작
```

### GitLab CI (services 방식)

```yaml
# .gitlab-ci.yml
test:unit:
  script:
    - uv sync --frozen
    - uv run pytest tests/unit/ -q

test:integration:
  services:
    - postgres:16-alpine
  variables:
    POSTGRES_DB: testdb
    POSTGRES_USER: test
    POSTGRES_PASSWORD: test
    DATABASE_URL: "postgresql://test:test@postgres/testdb"
  script:
    - uv sync --frozen
    # services 방식은 testcontainers 대신 DATABASE_URL 직접 사용 필요
    - uv run pytest tests/integration/ -v
```

> **Note**: GitLab services 방식은 `testcontainers`를 우회하고 DATABASE_URL을 직접 주입해야 합니다.
> `integration/conftest.py`의 `pg` fixture를 환경변수 기반으로 교체하거나,
> `TESTCONTAINERS_HOST_OVERRIDE` 환경변수로 소켓 경로를 재지정하는 방법을 사용합니다.

---

## JSONB 테스트 항목 (`test_jsonb_queries.py`)

| 클래스 | 검증 내용 |
|--------|----------|
| `TestDesignConditionsJsonb` | `->>` 텍스트 추출, 중첩 경로 `["isp0"]["required_bitdepth"]`, 복합 조건 |
| `TestFeatureFlagsJsonb` | `@>` containment, `?` 키 존재, GIN 인덱스 존재 확인, EXPLAIN 플랜 |
| `TestGeneratedColumns` | `sw_version_hint` 값 일치, 인덱스 존재, GROUP BY 집계 |
| `TestRawJsonbOperators` | `->>`/`#>>` 연산자 raw SQL, `@>` containment raw SQL |
