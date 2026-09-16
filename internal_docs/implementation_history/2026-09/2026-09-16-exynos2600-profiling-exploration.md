# Exynos2600 profiling / exploration 구현·검증 기록

- 일자: 2026-09-16
- 브랜치: `feat/exynos2600-profiling-exploration`
- 기준 commit: `f377e78679061797290ded44c88b6e9736309dc2`
- 계획: `E:/50_Codex_Soc_Scenario_DB/2026-09-16_exynos2600-simulation-architecture-improvement-plan.md`
- 상태: 1차 구현 완료, P0~P9 전체 계획은 미완료. 정식 reference fixture 승격은 차단 상태.

## 구현

1. SourceModel envelope로 IP의 BW/DVFS/power/performance/SW 모델 블록과 SoC platform_model을 보존. formula 문자열은 실행하지 않는다. sample_rates_khz/csc, scenario provenance 지원.
2. Alembic 0017: HW runtime, SW event latency, parametric_sweeps, provenance, platform_model JSONB 저장. scenario write/export 및 read schema 연동.
3. Perfetto 일반 HW track/SW thread slice, 고유 invocation ID, 정수 ns timestamp, origin-relative chart time, flow 기반 sequence. HW/SW runtime avg(min/mean/max), 명시적 predecessor event latency 통계. source_anchor 명시, 음수 latency/중복 mapping/required 누락 오류.
4. Summary-only import, HW/SW/latency metric observations, raw trace hash/size, import fingerprint. 동일 ID의 다른 profiling evidence 덮어쓰기 거부. summary에 허위 timeline/p95 생성 없음.
5. 버전 고정 timing profile 생성 CLI, source evidence/hash/project/scenario/variant/context 검증, selected statistic과 정확한 edge latency 반영. baseline 불변, profile cache 포함, run_info/derived_from 저장. SW stage의 HW time budget도 선택 statistic으로 반영.
6. Measurement 화면의 HW/SW sequence와 HW runtime/SW latency 표. 기존 timing chart 재사용.
7. operating_modes.max_clock_mhz 상한 연결. import bundle preview에서 실제 variant 상속 해석.
8. 기존 scenario OFAT preview API: resolved baseline, node clock/SW margin 축, case/input hash, 제한 적용, DB 무변경. 불완전한 전력의 전체 합은 unknown; known subtotal 구분.
9. Read-only fixture 비교 manifest script, 입력 예제, 가이드와 계약 문서.

## 검증 결과

| 검증 | 결과 |
|---|---|
| 전체 단위 테스트 + coverage | 1,228 passed, 81.42%, 80% gate 통과 |
| 이후 추가 회귀/영향 범위 | meas_import + sim + measurement UI 267 passed; 마지막 importer 80 passed |
| 전체 PostgreSQL 통합 테스트 | 162 passed |
| 마지막 profile replay/API/JSONB 검증 | 2 passed |
| Ruff | 전체 통과 |
| mypy | 저장소 설정 대상 16 files 통과 |
| Workbench | 36 tests 통과, TypeScript/Vite build 통과 |
| 의존성 | frozen sync 통과, profiling extra 포함 runtime pip-audit 알려진 취약점 없음 |
| 실제 Perfetto Trace Processor | 합성 Chrome trace 입력: HW 2ms / SW 1ms / latency 1ms / flow 연결 확인 |
| Summary CLI | 합성 예제 YAML 생성/검증 성공, 재실행 및 충돌 거부 테스트 |
| 기존 v15 fixture | strict ETL·IS v15/priority camera 회귀 통과, 원본 fixture 변경 없음 |
| 참조 fixture | 46 documents schema 적재 성공, strict semantic ETL 실패(23 selected_mode 불일치) |

전체 coverage 실행 후 추가한 테스트 2개는 별도 통과했으며 coverage 수치는 마지막 전체 coverage 실행의 수치다. 실제 사내 .pftrace는 제공되지 않아 실측 capture 인수 검증은 미실행이다. 실제 Streamlit 화면을 브라우저에서 새로 조작하는 시각 QA는 미실행이다. pytest의 기존 Starlette/httpx deprecation warning 1건이 있다.

## 원본 승격 차단 근거

격리 PostgreSQL에서 schema skip은 0건이었다. semantic validation은 아래 23건을 발견했다.

- MTNR: Capture_SF, Capture_MF, Remosaic, Preview 참조와 catalog supported mode 불일치 13건.
- MFC: HighSpeed/LowPower 참조와 catalog supported mode 불일치 10건.

지원 모드나 성능을 임의로 만들어 통과시키지 않았다. 원본과 현행 v15를 덮어쓰거나 합치지 않았다. manifest와 strict ETL 보고서는 부모 폴더에 저장했다.

- `2026-09-16-exynos2600-fixture-manifest.json`
- `2026-09-16-exynos2600-staging-etl-report.json`

## 미완료 범위

- P0 namespace 분리된 정식 staging fixture 생성과 승격 정책 완결; 현재는 read-only manifest와 격리 DB 검증.
- P1 SourceModel 내부 driver별 typed executable model 및 전체 roundtrip 세부 검증.
- P2 사내 trace correlation/frame/stream/clock 품질 보고, profile partial update/default pointer/승인 UI. 현재 profile은 명시 선택 revision 방식이며 전체 catalog revision fingerprint는 아직 없음.
- P3~P5 heterogeneous throughput, driver vote/physical traffic 분리, platform DVFS consumer, CPU active power와 전압/계수 특성화. 일부 입력 저장과 clock 상한만 구현.
- P6 measured A/B frame alignment와 profile 선택 UI, 추가 architecture 축/explicit 조합.
- P7~P8 OTF/SRAM/LLC capacity·traffic/area/Pareto/차기 SoC 투영.
- P9 참조 mode 불일치 해결 후 13 UC 전체 승격, 실제 사내 capture·시각 QA 인수.

전력·면적 최적화나 전체 계획 완료를 의미하지 않는다. 현재 구현은 실측 데이터를 내부에서 반복 입력하고 추적 가능한 timing profile로 실행하는 경로와 제한된 기존 scenario 탐색을 제공한다.

## 사용 문서

`implementation/docs/guides/profiling-and-scenario-exploration.md`에 설치, migration, summary/trace meta, profile 생성과 API 적용, 탐색 API 및 제한을 기록했다. 실제 운영 DB migration, main merge, 원격 push는 수행하지 않았다.


## 후속 실행 및 구현 기록 — 2026-09-16

### 실행 중인 로컬 서비스

- API: http://127.0.0.1:18000/docs (`/health/ready`: DB connected, simulation dependencies available)
- UI: http://127.0.0.1:18502/ (Evidence Dashboard: `/Evidence_Dashboard`)
- PostgreSQL: 127.0.0.1:15432, 기존 Docker volume 유지
- pgAdmin: http://127.0.0.1:15050/
- 기존 DB migration 0016 → 0017 적용. 시작 시 project 1/scenario 13/variant 212/evidence 40 확인.
- API/UI는 hidden background process로 실행. runtime_logs/profiling-20260916에 로그와 PID 기록. 인증을 해제하지 않고 프로세스 전용 임시 analyst/writer key로 UI → API 실행 연결. 키를 파일/문서/Git에 저장하지 않음.

### 추가 구현

- `POST /evidence/{id}/timing-profile`: 저장된 measurement와 현재 resolved baseline에서 profile 준비, DB 무변경.
- Evidence Dashboard의 Calculation → Use measured timing profile: capture 선택, 통계/context 확인, task mapping, revision/statistic 지정, profile 다운로드/업로드, preview 실행. 기존 confirm/save 흐름 재사용.
- baseline fingerprint에 topology, size profile, resolved variant, project metadata/globals, IP catalog, SoC metadata 반영. 변경된 모델로 replay하려면 profile 재준비.
- source_task_mapping이 포함된 profile의 runtime/latency가 원본 측정값과 다른 경우 거부.
- FPS 외삽, active runtime을 wall duration으로 대체, 알 수 없는 task mapping 거부. latency-only profile의 명시적 event mapping도 지원.
- UI replay는 capture 실행 context를 보존하고 일반 form 기본 thermal/inline DVFS를 섞지 않음.

### 검증

- 영향 범위 단위 테스트 450개 통과; 마지막 latency-only 회귀 포함 profiling 테스트 11개 통과.
- PostgreSQL profile 준비/실행/값 변조 및 baseline hash 거부 통합 테스트 2개 통과.
- Ruff 전체 및 저장소 설정 mypy 통과.
- 실제 브라우저: Evidence Dashboard 렌더링, 기존 측정 capture 선택, profile 준비 API 호출 확인. 기존 측정 min_ms 누락 시 422로 거부됨(정상 동작). 완전한 capture 생성/실행은 격리 DB 통합 테스트로 검증.
- 실제 브라우저: 일반 Run Preview 성공, preview-only/not saved 표시 확인. 데이터 저장 버튼은 누르지 않음.
- 브라우저 첫 multipage 접속 시 Streamlit의 nested health/host-config 404 fallback 및 기존 iframe feature 경고 관찰; 최종 페이지 렌더링과 실제 API 실행 성공.

### 남은 범위

모드 불일치 23건, driver 모델 실행 consumer, CPU 전력, LLC/area/Pareto, 실제 사내 .pftrace 인수는 여전히 남아 있다. 기존 측정의 min_ms 누락은 추정값으로 채우지 않았다. UI에서 사용할 새 capture에는 min/mean/max와 samples를 제공해야 한다. 중앙 profile registry/승인/default pointer와 measured A/B frame alignment는 이번 변경에 포함되지 않는다.
