# 예측 협업·자연어 What-if 검증

Status: Verified locally. Date: 2026-10-14.
Branch: `feat/prediction-collaboration-query`.
Base: `5ae2916c1cdf7bb99eed068b23e0c6bf681caa40`.

## 구현 범위

- 예측별 상세 설명·태그·작성자·수정 revision과 댓글·답글.
- 검토한 current 예측을 확인하는 등록 사전조건과 동시 수정 409 안내.
- guarded lever의 IQ review·탐색·예측 등록 원자성 및 FK 잠금과의 호환성.
- 한국어/영어의 크기·FPS·노드 clock 하한 질문을 구조화 조건으로 해석하고 비교.
- 기준·변경 입력 hash 검사, 서버 재계산, 개인/공유 frozen 실험과 조건 재실행.
- 현재 창 메모리에 보관하는 API 인증 정보, 계정·선택·질문 변경 시 응답 격리.

## 실행 결과

| 검사 | 결과 |
| --- | --- |
| frozen dependency sync | 기존 설치 111 packages 확인; lockfile 변경 없음 |
| 전체 단위 테스트 | 1,949 passed, 6 skipped; coverage 80.19% |
| 최종 수정 경로 집중 회귀 | 78 passed; combined coverage 80.30%, 80% gate 통과 |
| PostgreSQL 관련 통합 테스트 | 35 passed; 새 마이그레이션과 실제 동시 등록·rollback·deadlock 회귀 포함 |
| React UI 테스트 | 232 passed, 11 skipped |
| React typecheck / production build | 통과 |
| Ruff / diff whitespace | 통과 |
| 신규 What-if 5파일 focused mypy | `--follow-imports=silent` 통과 |
| 전체 mypy | 기준 커밋 archive와 기능 브랜치 모두 372 errors / 28 files; 추가 오류 0 |
| npm audit | 자동 승인 심사가 npm registry 외부 전송을 거부; 사용자 승인 대기 |

전체 mypy의 기존 오류와 미실행 보안 조회 때문에 전체 CI 준비 완료로 판정하지 않는다.
외부 전송 승인 없이 보안 조회를 우회하지 않았다. 기존 Starlette/httpx deprecation
warning 및 기존 선택적 테스트 skip은 실행 결과에 포함한다.

단위 테스트는 `tests/unit`을 4 workers로 실행했다. 최종 집중 회귀는
`test_arch_services.py`, `test_prediction_discussion.py`, `test_scenario_whatif.py`,
`tests/unit/sim/test_scenario_whatif.py`, `test_collaboration_cors.py`를 실행했다.
통합 테스트는 `test_prediction_collaboration.py`, `test_scenario_whatif.py`,
`test_lever_register.py`, `test_timing_workbench.py`, `test_arch_exploration.py`를
별도 PostgreSQL 컨테이너에서 실행했다.

## 실제 화면 확인

별도 PostgreSQL DB에 기존 fixture를 strict ETL로 로드하고 로컬 API·UI를 실행했다.
`uc-cam-recording-e2600 / cam-rec-r1-uhd30-vdis`에서 센서 입력을 유지하고
`record_out`을 3840×2160에서 1920×1080으로 변경했다.

- 모델 전력 합계: 788.22 → 686.16 mW.
- BW: 5367.20 → 4247.50 MB/s.
- MFC 요구 clock: 41.5 → 20.7 MHz; 적용 clock: 133 → 133 MHz.
- DVFS 최소 단계 유지 이유, 미모델·제외 성분, 고정 SW 가정을 화면에서 확인.
- 질문 해석 → 조건 확인 → 계산 → 설명을 포함한 실험 저장 성공.
- 등록 예측 상세 설명과 댓글 저장 및 작성자/revision 표시 성공.

수치는 sample DVFS와 기본 모델을 사용한 fixture 검증 결과이며 실측 결론이 아니다.
화면 캡처는 Git-ignored `output/whatif-browser.jpg`에 보관했다.

## 적용 경계

새 테이블은 migration `0024`로 추가하며 운영 DB에는 적용하지 않았다.
별도 작업 폴더에서 구현했고 동시에 진행된 원본 작업의 변경을 보존했다.
병렬 ModelBasis 작업에도 `0024` migration이 있으므로 두 작업을 병합할 때 revision
번호와 선행 관계를 정리해야 한다. 이 문서의 결과는 이 브랜치 단독 검증이다.

사용법: [예측 설명·댓글과 자연어 What-if](../guides/prediction-collaboration-whatif.md).
