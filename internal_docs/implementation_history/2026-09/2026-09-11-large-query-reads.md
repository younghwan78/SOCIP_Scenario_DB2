# 대규모 조회 최적화 — 2026-09-11

기준 커밋: `bcee4a3`. 작업 브랜치: `perf/large-query-reads`.

## 구현 범위

- Query: variant/severity 조건을 시나리오 SQL EXISTS에 반영해 pipeline을 가진
  시나리오 후보를 먼저 줄인다. AND 그룹 및 같은 필드의 equality OR 그룹도
  사전 필터에 반영하며, 기존 최종 조건·집계·정렬·페이지 의미를 유지한다.
- 상속: severity 미지정 자식은 부모 값을 확인할 때까지 후보에 포함한다.
  부모는 scenario/variant 복합키로 읽어 다른 시나리오의 동명 variant 혼입을 막는다.
- Evidence: 시간·ID 선택용 필드를 먼저 읽고 선택된 최신 simulation의 KPI/context만
  읽는다. timezone, 무효/누락 timestamp, ID 동률 정책 및 이력 상한을 유지한다.
- Canonical graph: 선택 variant와 부모만 적재한다. 120개 sibling을 추가한 테스트에서
  선택 1행 + 부모 1행만 읽고 기존 상속 결과와 동일함을 검증했다.
- 목록: `/api/v1/catalog/{kind}` 요약 API로 pipeline/globals/overlay를 제외한다.
  기존 상세/목록 API 응답은 유지한다. 목록은 SQL에서 검색·정렬·페이지를 처리한다.
- SPA: 모든 페이지를 다운로드하던 경로를 제거하고 100행씩 조회한다.
  검색 지연 250ms, 요청 취소, 범위 변경 시 페이지 초기화, 페이지 밖 선택 ID 복원을 지원한다.

## PostgreSQL 계측

`scripts/bench_large_reads.py`는 별도의 PostgreSQL 16 컨테이너를 생성하고
로컬 Git의 기준 코드를 읽어 현재 구현과 동일 데이터로 비교한다. 운영 DB는 사용하지 않는다.
실행: `uv run python scripts/bench_large_reads.py --baseline-ref bcee4a3`

합성 데이터: 시나리오 1,500개(각 pipeline padding 8KiB), variant 1,500개,
한 variant의 simulation 이력 3,000개(각 context/result padding 합계 8KiB).
워밍업 후 7회 측정. 메모리는 별도 실행의 tracemalloc peak다.

| 지표 | 이전 | 이후 |
| --- | ---: | ---: |
| 선택 variant Query 중앙값 | 334.06ms | 37.49ms |
| Query 표본 p95 | 353.38ms | 49.62ms |
| Query 동시 4요청, 12표본 p95 | 714.15ms | 158.04ms |
| Query Python peak | 48.46MiB | 7.45MiB |
| Query SQL 횟수 | 10 | 11 |
| Query 반환 JSON | 881 bytes | 881 bytes |
| 목록 100행 중앙값 | 4.69ms | 3.44ms |
| 목록 100행 JSON | 844,716 bytes | 16,761 bytes |
| 목록 100행 Python peak | 1.07MiB | 0.17MiB |

두 단계 evidence 읽기로 SQL은 1회 증가하지만 큰 이력 payload를 줄인다.
결과 내용의 동등성은 계측 스크립트에서도 assert한다. EXPLAIN ANALYZE/BUFFERS를
포함한 원본 결과는 로컬 `output/large-reads/benchmark.json`에 저장된다.
표본이 적고 합성 payload를 사용한 개발 환경 측정이며 운영 응답 시간 보장은 아니다.

## 검증

- 전체 Python 단위·격리 PostgreSQL 통합: 1,333 passed.
- SPA: 13 tests, lint, TypeScript/Vite build 통과.
- Ruff 통과, 설정된 mypy 16파일 범위 통과.
- Chrome + 실제 API + 격리 PostgreSQL + 프로덕션 SPA 번들:
  초기 다음 페이지 자동 다운로드 없음, 다음/마지막 페이지 경계, 선택 유지,
  서버 검색 및 페이지 초기화, 250번째 항목 URL 복원/새로고침 확인.
- 브라우저 재로드 후 콘솔 오류 0건. 첫 진입에서 기존 favicon.svg 404가 있었으며
  본 변경과 관련된 목록/API 오류는 없었다.
- 로컬 로그와 브라우저 이미지는 `output/large-reads/`에 있으며 Git 대상에서 제외한다.

## 유지되는 경계

복잡한 topology/상속 axis/음수 조건과 전체 결과 집계는 Python 후보 평가를 유지한다.
Query history의 identity/time 필드는 여전히 이력 수에 비례해 읽으며 기존 상한을 유지한다.
Canonical graph의 evidence를 최신 1개로 줄이지 않는다. 이력별 rule context가 달라질 수 있다.
검색은 일반 부분 문자열 검색으로, 대규모 텍스트 검색용 인덱스를 추가하지 않았다.
이번 변경에 스키마 migration이나 실제 fixture 수정은 없다. 비교/저장 및 가상화는 별도 범위다.
