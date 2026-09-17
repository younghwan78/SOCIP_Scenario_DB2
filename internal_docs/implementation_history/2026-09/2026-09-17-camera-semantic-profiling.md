# Camera semantic profiling 구현 및 검증

날짜: 2026-09-17
브랜치: feat/exynos2600-profiling-exploration
상태: 구현 및 로컬 검증 완료. 실제 사내 capture 인수 검증은 데이터 제공 후 수행해야 한다. 이번 변경은 working tree에 있으며 push/merge하지 않았다.

## 구현한 흐름

1. scenario별 MD의 camera-profile-v1 YAML 블록 → 정규화 → preview → hash 확인 → PostgreSQL transaction 저장.
2. execution_path_id, pipeline_model, stage_timing, profiling_metadata 추가(Alembic 0018). 기존 통계 JSONB 유지, 기존 row NULL 유지.
3. Task/edge 참조, active/bypass 상태, workload, runtime scope, min/mean/max/samples 검증. 불명확한 통계 count와 누락 runtime을 만들지 않음.
4. semantic trace는 로컬 CLI에서 제한된 시간창만 읽음. logical task_id와 동일한 slice 이름 사용. sequence-only 처리로 MD 통계는 유지. flow와 선언 edge 불일치 거부.
5. 별도 SW projection: 명시적 source→target mapping, task/latency별 scale 또는 delta, source/target hash 재검증. HW 및 inclusive stage runtime projection 거부. 원본 불변.
6. 기존 제한된 clock 후보 탐색에 연결. 각 후보의 HW time/BW/known power, required/set clock 출력. CPU power 미상은 전체 power 미상으로 유지.
7. Camera Profiling UI와 Evidence Dashboard의 semantic graph/통계 표시. RT/NRT chain span 비교 API/UI 추가.
8. 기존 measured-profile workflow 유지. Curated camera capture가 legacy replay로 HW 값을 덮어쓰는 우회는 차단.

## 검증 결과

- 전체 단위 회귀: 1,254 passed, coverage 80.75% (80% gate 통과).
- 후속 변경 관련 import/simulation/API/dashboard 테스트: 281 passed.
- 추가된 camera 경계조건/화면 및 clock 출력 테스트: 31 passed.
- 전체 PostgreSQL 통합 테스트: 163 passed. Testcontainers PostgreSQL 사용, SQLite 대체 없음.
- Ruff 전체 및 설정된 mypy 16개 파일 통과.
- 새 migration을 격리 DB 초기 상태부터 적용하고 로컬 기존 DB 0017→0018 적용.
- 실제 Perfetto TraceProcessor에서 합성 trace 3 events 추출. MD runtime 통계 불변과 artifact SHA256 기록 확인. 사내 binary .pftrace 검증과 구분.
- Playwright: Camera Profiling 실제 페이지 진입, MD 파일 업로드, authenticated preview, 경로/SW version/통계/Save 버튼 표시 확인. 합성 데이터를 운영용 로컬 evidence로 저장하지 않음.
- UI 진입 시 기존 Streamlit multipage health/host-config 경로 fallback 404 두 건이 발생했으나 정상 페이지 및 preview 로드 성공.
- API readiness/UI HTTP 200, 무인증 import commit HTTP 401 확인.
- 전체 테스트에서 발견한 이전 simulation mock의 derived_from 누락은 fixture를 보완함.

검증 시점 이후 최종 변경에 대해서는 해당 범위 테스트를 다시 실행했다. 동일 검사 반복을 최종 전체 CI 수행으로 표현하지 않는다. 의존성/lockfile과 frontend bundle은 변경하지 않았다.

## 현재 실행

- UI: http://127.0.0.1:18502/Camera_Profiling
- API: http://127.0.0.1:18000/docs
- DB: 127.0.0.1:15432
- pgAdmin: http://127.0.0.1:15050

API/UI는 기존 로컬 launcher를 사용해 숨김 background process로 실행. 인증 secret은 프로세스 환경에서만 전달하며 문서에 기록하지 않음.

## 사내 입력 준비

실행 가능한 producer 예제:
`implementation/examples/measurement-import/camera/scenario-statistics.md`

운영 가이드:
`implementation/docs/guides/camera-semantic-profiling.md`

초기 설계 문서의 설명용 sw_baseline_ref 단독 필드 대신 실제 입력은 기존 execution_context(silicon_rev/sw_baseline_ref/thermal)를 사용한다. sw_baseline_ref는 DB에 등록된 SW profile ID이다. node_refs/workload는 현재 scenario/variant에 맞춰야 한다.

## 적용 범위와 남은 인수 사항

- 사내 semantic.pftrace와 MD의 실제 label/통계 경계가 아직 제공되지 않아 해당 형식의 인수 검증은 남아 있다.
- 초기 trace 계약은 정확한 logical slice name matching이다. 자동 regex 추정, frame/stream correlation 추론, 임의 MD 표 parsing을 추가하지 않았다.
- target_path_id는 label이고 실제 EIS/GDC/LME/DOF 활성 여부는 target variant topology가 결정한다. path label만 변경해 HW/BW를 바꾸지 않는다.
- Projection은 frame당 1회 exclusive SW와 same-frame end-to-start gap을 지원한다. HW 포함 aggregate stage는 먼저 분해해야 한다.
- RT/NRT 비교는 boundary span 진단값이다. clock/workload/model revision 일치가 별도로 확인되지 않아 validated=false를 유지한다.
- Clock 탐색은 제공된 후보에 대한 OFAT 평가이다. 다변수 자동 최적화, 합법 OPP 전수 탐색, CPU active power calibration은 이번 구현에 포함하지 않았다.
