# ScenarioDB 사내 Staging 검증 및 Main Merge 체크리스트

## 1. 목적과 사용 방법

이 문서는 release candidate 브랜치를 사내 staging 환경에서 검증한 뒤
`main` 병합 여부를 결정하기 위한 승인 기록입니다.

- 모든 항목은 `PASS`, `FAIL`, `N/A` 중 하나로 기록합니다.
- `N/A`에는 적용되지 않는 이유와 승인자를 남깁니다.
- 비밀번호, 토큰, 인증서 원문, 사내 URL, 실제 사용자·그룹 ID는 이 문서나
  GitHub PR에 기록하지 않습니다.
- 실행 로그에는 민감정보를 제거하고, 사내에서 승인된 증적 저장소의 참조
  번호나 링크만 남깁니다.
- 테스트 데이터는 synthetic fixture를 우선 사용합니다.
- 하나라도 Merge Blocker가 `FAIL`이면 `main`에 병합하지 않습니다.

## 2. 검증 대상 기록

| 항목 | 기록 |
| --- | --- |
| PR | `<PR_NUMBER_OR_URL>` |
| 검증 commit SHA | `<FULL_COMMIT_SHA>` |
| 대상 환경 | `<INTERNAL_STAGING_ENVIRONMENT>` |
| 검증 일시 | `<YYYY-MM-DD HH:MM TZ>` |
| 배포 담당자 | `<OWNER_OR_TEAM>` |
| 검증 담당자 | `<OWNER_OR_TEAM>` |
| 승인 담당자 | `<OWNER_OR_TEAM>` |
| 롤백 대상 commit/tag | `<KNOWN_GOOD_REVISION>` |
| 증적 위치 | `<INTERNAL_EVIDENCE_REFERENCE>` |

검증 도중 새 commit이 push되면 기존 결과를 그대로 재사용하지 않습니다.
최소한 GitHub 필수 CI와 변경 영향 영역의 staging 항목을 새 SHA 기준으로
다시 수행합니다.

## 3. Merge Blocker 요약

다음 항목은 반드시 `PASS`여야 합니다.

- [ ] MB-01 검증 SHA와 PR head SHA가 일치한다.
- [ ] MB-02 GitHub `quality`와 `integration`이 성공했다.
- [ ] MB-03 staging health/readiness가 정상이다.
- [ ] MB-04 인증 우회 설정이 비활성화되어 있다.
- [ ] MB-05 SSO 또는 승인된 임시 인증 경로의 401/403/RBAC 검증을 통과했다.
- [ ] MB-06 DB migration과 rollback/restore 절차를 검증했다.
- [ ] MB-07 서비스 계정의 DB·아티팩트 경로 권한이 최소 권한으로 동작한다.
- [ ] MB-08 주요 API와 Dashboard smoke test를 통과했다.
- [ ] MB-09 심각도 Critical/High 보안 또는 데이터 무결성 문제가 없다.
- [ ] MB-10 실제 rollback 명령과 담당자가 확정되어 있다.

## 4. 코드와 배포 산출물

| ID | 확인 사항 | 기대 결과 | 상태 | 증적/비고 |
| --- | --- | --- | --- | --- |
| REL-01 | PR head와 배포 SHA 비교 | SHA가 정확히 일치 | `<STATUS>` | `<EVIDENCE>` |
| REL-02 | GitHub 필수 체크 | `quality`, `integration` 성공 | `<STATUS>` | `<EVIDENCE>` |
| REL-03 | 패키지 설치 | lockfile 기준 설치 성공 | `<STATUS>` | `<EVIDENCE>` |
| REL-04 | Alembic head | 예상 단일 head 확인 | `<STATUS>` | `<EVIDENCE>` |
| REL-05 | 설정 검증 | 필수 환경변수 누락 없이 시작 | `<STATUS>` | `<EVIDENCE>` |
| REL-06 | 민감정보 검사 | 저장소·로그·응답에 secret 없음 | `<STATUS>` | `<EVIDENCE>` |

권장 명령 예시:

```bash
git rev-parse HEAD
uv sync --frozen --group dashboard --group sim
uv run alembic heads
uv run alembic upgrade head
```

## 5. SSO/OIDC와 RBAC

SSO가 아직 연결되지 않았다면 승인된 임시 API-key 경로로 RBAC를 검증하고,
SSO 검증 항목은 별도의 후속 blocker 또는 명시적 `N/A` 승인으로 처리합니다.
운영 전환 시에는 사람 계정과 자동화 service account를 분리합니다.

| ID | 확인 사항 | 기대 결과 | 상태 | 증적/비고 |
| --- | --- | --- | --- | --- |
| IAM-01 | issuer/audience/JWKS 검증 | 승인된 IdP 토큰만 수락 | `<STATUS>` | `<EVIDENCE>` |
| IAM-02 | 토큰 없음 | HTTP 401 | `<STATUS>` | `<EVIDENCE>` |
| IAM-03 | 만료·변조·잘못된 audience | HTTP 401, 토큰 내용 미노출 | `<STATUS>` | `<EVIDENCE>` |
| IAM-04 | 역할 부족 | HTTP 403 | `<STATUS>` | `<EVIDENCE>` |
| IAM-05 | `analyst` | Simulation/Exploration만 허용 | `<STATUS>` | `<EVIDENCE>` |
| IAM-06 | `writer` | Write/export 허용, admin/delete 거부 | `<STATUS>` | `<EVIDENCE>` |
| IAM-07 | `admin` | delete/admin endpoint 허용 | `<STATUS>` | `<EVIDENCE>` |
| IAM-08 | 그룹 매핑 | 미매핑 그룹은 권한을 얻지 못함 | `<STATUS>` | `<EVIDENCE>` |
| IAM-09 | 감사 주체 | 신뢰된 subject가 actor로 기록 | `<STATUS>` | `<EVIDENCE>` |
| IAM-10 | 로컬 bypass | `SCENARIO_DB_MUTATION_AUTH_DISABLED=false` | `<STATUS>` | `<EVIDENCE>` |
| IAM-11 | 레거시 API 키 | 유지/폐기 일정과 소유자 확정 | `<STATUS>` | `<EVIDENCE>` |
| IAM-12 | 로그 안전성 | JWT/API key/인증서 원문 미기록 | `<STATUS>` | `<EVIDENCE>` |

## 6. 네트워크, TLS, 조회 API

현재 application read endpoint는 자체 인증을 강제하지 않으므로 사내
reverse proxy와 네트워크 정책이 보안 경계입니다.

| ID | 확인 사항 | 기대 결과 | 상태 | 증적/비고 |
| --- | --- | --- | --- | --- |
| NET-01 | 외부 직접 접근 | 승인되지 않은 네트워크에서 차단 | `<STATUS>` | `<EVIDENCE>` |
| NET-02 | TLS | 승인된 인증서·프로토콜 사용 | `<STATUS>` | `<EVIDENCE>` |
| NET-03 | proxy header | 외부 사용자가 신뢰 헤더를 위조할 수 없음 | `<STATUS>` | `<EVIDENCE>` |
| NET-04 | read endpoint | proxy/ACL 정책에 따라 접근 제한 | `<STATUS>` | `<EVIDENCE>` |
| NET-05 | CORS | 승인된 UI origin만 허용 | `<STATUS>` | `<EVIDENCE>` |
| NET-06 | admin endpoint | 승인된 운영 네트워크에서만 노출 | `<STATUS>` | `<EVIDENCE>` |
| NET-07 | PostgreSQL | application subnet/service account만 접근 | `<STATUS>` | `<EVIDENCE>` |

## 7. 데이터베이스와 데이터 무결성

| ID | 확인 사항 | 기대 결과 | 상태 | 증적/비고 |
| --- | --- | --- | --- | --- |
| DB-01 | 사전 백업 | 복구 가능한 staging 백업 생성 | `<STATUS>` | `<EVIDENCE>` |
| DB-02 | migration | `alembic upgrade head` 성공 | `<STATUS>` | `<EVIDENCE>` |
| DB-03 | 재시작 | migration 후 API readiness 정상 | `<STATUS>` | `<EVIDENCE>` |
| DB-04 | Write API | stage → validate → diff → apply 성공 | `<STATUS>` | `<EVIDENCE>` |
| DB-05 | stale revision | 변경된 batch apply가 거부됨 | `<STATUS>` | `<EVIDENCE>` |
| DB-06 | 동시 persist | 동일 simulation insert 경쟁이 수렴 | `<STATUS>` | `<EVIDENCE>` |
| DB-07 | backup restore | 별도 staging DB로 복원 확인 | `<STATUS>` | `<EVIDENCE>` |
| DB-08 | 최소 권한 | app 계정에 불필요한 DDL/admin 권한 없음 | `<STATUS>` | `<EVIDENCE>` |
| DB-09 | fixture 경계 | 검증 데이터가 승인된 synthetic fixture임 | `<STATUS>` | `<EVIDENCE>` |

## 8. Simulation/Exploration 용량과 장애 동작

제한값은 worker별로 적용됩니다. 시스템 전체 최대 동시 실행 수는 API
worker 수를 포함해 계산합니다.

| ID | 확인 사항 | 기대 결과 | 상태 | 증적/비고 |
| --- | --- | --- | --- | --- |
| CAP-01 | 정상 simulation | 제한 이내 요청 성공 | `<STATUS>` | `<EVIDENCE>` |
| CAP-02 | 정상 exploration | 제한 이내 compile/preview 성공 | `<STATUS>` | `<EVIDENCE>` |
| CAP-03 | 동시 실행 초과 | HTTP 429와 `Retry-After` 반환 | `<STATUS>` | `<EVIDENCE>` |
| CAP-04 | timeline frame 초과 | HTTP 422 | `<STATUS>` | `<EVIDENCE>` |
| CAP-05 | sweep case 초과 | 확장 전에 요청 거부 | `<STATUS>` | `<EVIDENCE>` |
| CAP-06 | 요청 크기 초과 | HTTP 413 | `<STATUS>` | `<EVIDENCE>` |
| CAP-07 | graph 구성요소 초과 | 제한 설명과 함께 거부 | `<STATUS>` | `<EVIDENCE>` |
| CAP-08 | 부하 중 health | readiness와 기본 조회가 허용 범위 유지 | `<STATUS>` | `<EVIDENCE>` |
| CAP-09 | capacity 계산 | worker 수·CPU·메모리 기준값 기록 | `<STATUS>` | `<EVIDENCE>` |

용량 기준 기록:

| 항목 | 값 |
| --- | --- |
| API worker 수 | `<VALUE>` |
| worker별 simulation 동시 실행 | `<VALUE>` |
| worker별 exploration 동시 실행 | `<VALUE>` |
| 관찰된 최대 메모리 | `<VALUE>` |
| 관찰된 p95 응답 시간 | `<VALUE>` |
| 승인된 운영 한계 | `<VALUE>` |

## 9. 아티팩트 수명주기

| ID | 확인 사항 | 기대 결과 | 상태 | 증적/비고 |
| --- | --- | --- | --- | --- |
| ART-01 | 정상 export | 세 파일이 한 generation으로 게시 | `<STATUS>` | `<EVIDENCE>` |
| ART-02 | 저장 경로 | API/DB에 host 절대경로 없음 | `<STATUS>` | `<EVIDENCE>` |
| ART-03 | 권한 | service account만 report root 쓰기 가능 | `<STATUS>` | `<EVIDENCE>` |
| ART-04 | DB commit 실패 | 새 generation만 제거 | `<STATUS>` | `<EVIDENCE>` |
| ART-05 | 재-export | 새 metadata 연결 후 이전 generation 정리 | `<STATUS>` | `<EVIDENCE>` |
| ART-06 | reconciliation dry-run | missing/mismatch/orphan/staging 탐지 | `<STATUS>` | `<EVIDENCE>` |
| ART-07 | apply 범위 | stale staging만 명시적으로 제거 | `<STATUS>` | `<EVIDENCE>` |
| ART-08 | custom path | production에서 비활성화 | `<STATUS>` | `<EVIDENCE>` |

권장 점검:

```bash
scenario-db-reconcile-artifacts
```

`missing_file`, `checksum_mismatch`, `invalid_path`가 있으면 Merge Blocker로
취급합니다. `orphan_file`은 원인을 확인하고 보존 또는 정리 결정을 기록합니다.

## 10. 관측성 및 운영 절차

| ID | 확인 사항 | 기대 결과 | 상태 | 증적/비고 |
| --- | --- | --- | --- | --- |
| OPS-01 | liveness/readiness | 모니터링에서 정상 판정 | `<STATUS>` | `<EVIDENCE>` |
| OPS-02 | 구조화 로그 | 요청 실패 원인 추적 가능 | `<STATUS>` | `<EVIDENCE>` |
| OPS-03 | 민감정보 마스킹 | secret/token/내부 개인정보 미노출 | `<STATUS>` | `<EVIDENCE>` |
| OPS-04 | 401/403/429 관측 | 비정상 증가를 탐지 가능 | `<STATUS>` | `<EVIDENCE>` |
| OPS-05 | DB pool | 연결 고갈 없이 복구 | `<STATUS>` | `<EVIDENCE>` |
| OPS-06 | 디스크 사용량 | report root 임계치와 알림 설정 | `<STATUS>` | `<EVIDENCE>` |
| OPS-07 | 운영 담당자 | 장애 연락·에스컬레이션 경로 확인 | `<STATUS>` | `<EVIDENCE>` |

## 11. Rollback 검증

| ID | 확인 사항 | 기대 결과 | 상태 | 증적/비고 |
| --- | --- | --- | --- | --- |
| RB-01 | 이전 이미지/commit | 즉시 배포 가능한 revision 존재 | `<STATUS>` | `<EVIDENCE>` |
| RB-02 | 설정 rollback | 이전 환경변수 세트 복원 가능 | `<STATUS>` | `<EVIDENCE>` |
| RB-03 | DB 호환성 | downgrade 또는 restore 전략 승인 | `<STATUS>` | `<EVIDENCE>` |
| RB-04 | 실행 시간 | 목표 복구 시간 내 rollback 완료 | `<STATUS>` | `<EVIDENCE>` |
| RB-05 | rollback 후 smoke | health, read, write 핵심 경로 정상 | `<STATUS>` | `<EVIDENCE>` |

실제 rollback 명령은 사내 배포 시스템에 맞춰 별도 보안 문서에 관리하고,
이 저장소에는 내부 URL이나 credential을 넣지 않습니다.

## 12. 최종 승인

### 미해결 항목

| ID | 심각도 | 내용 | 소유자 | 기한 | Merge Blocker |
| --- | --- | --- | --- | --- | --- |
| `<ID>` | `<SEVERITY>` | `<DESCRIPTION>` | `<OWNER>` | `<DATE>` | `<YES/NO>` |

### 승인 판정

- [ ] 모든 Merge Blocker가 `PASS`다.
- [ ] `N/A` 항목의 사유와 승인자가 기록됐다.
- [ ] 미해결 non-blocker에 소유자와 기한이 있다.
- [ ] PR이 Draft에서 Ready for review로 전환됐다.
- [ ] 병합 직전 PR head SHA를 다시 확인했다.

| 역할 | 이름/팀 | 판정 | 일시 |
| --- | --- | --- | --- |
| 개발 검증 | `<OWNER>` | `<APPROVE/REJECT>` | `<TIMESTAMP>` |
| 운영 검증 | `<OWNER>` | `<APPROVE/REJECT>` | `<TIMESTAMP>` |
| 보안/IAM 검증 | `<OWNER>` | `<APPROVE/REJECT/N/A>` | `<TIMESTAMP>` |
| 최종 merge 승인 | `<OWNER>` | `<APPROVE/REJECT>` | `<TIMESTAMP>` |

최종 판정이 `APPROVE`이면 일반 merge commit으로 단계별 hardening commit을
보존하고, `main` CI 성공을 확인한 뒤 배포 tag를 생성합니다.
