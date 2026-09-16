# 실측 profiling과 기존 scenario 탐색

Status: Current · Last verified: 2026-09-16

근거: `meas_import/sequence.py`, `meas_import/timing_profile.py`, `sim/scenario_exploration.py`, `tests/integration/test_profiling_persistence.py`.

이 문서는 `feat/exynos2600-profiling-exploration`의 구현 범위와 사내 데이터 입력 방법을 설명한다. 예제 숫자는 합성 데이터이며 Exynos2600 실측 결과가 아니다.

## 설치와 DB

저장소 루트 `implementation/`에서 실행한다.

```powershell
uv sync --frozen --group dev --group dashboard --group sim --extra profiling
uv run alembic upgrade head
```

Migration `0017`은 `evidence.hw_task_timing`, `evidence.sw_event_latency`, `scenarios.parametric_sweeps`, `scenarios.provenance`, `soc_platforms.platform_model` JSONB 열을 추가한다. 실제 운영 DB의 migration은 배포 절차에서 수행한다. 개발 검증은 격리 PostgreSQL 컨테이너에서 수행했다.

Perfetto Python 패키지는 선택 의존성이다. Trace Processor 실행 파일은 최초 실행 시 내려받을 수 있다. 사내망에서는 승인된 Perfetto 실행 환경을 준비해야 한다.

## 1. 통계만 입력

예제: [meta-summary.yaml](../../examples/measurement-import/profiling/meta-summary.yaml).

```powershell
uv run python -m scenario_db.meas_import.cli --meta examples/measurement-import/profiling/meta-summary.yaml --out generated/profiling --strict
```

- HW runtime: `profiling.hw_task_timing`의 task, node_id, min_ms, mean_ms, max_ms, samples.
- SW runtime: `sw_task_timing`의 task, min_ms, mean_ms, max_ms, samples.
- SW latency: `profiling.sw_event_latency`의 edge_id, predecessor_task, successor_task, source_anchor, pairing, min_ms, mean_ms, max_ms, samples.
- avg는 canonical 필드 `mean_ms`에 넣는다. 단위는 모두 ms다.
- `min <= mean <= max`, 양수 표본 수, 유한한 수를 요구한다. 결측을 0으로 채우지 않는다.
- 통계만 입력하면 timeline이 생성되지 않는다. p95도 만들어내지 않는다.
- HW slice와 SW slice의 runtime은 wall duration이다. HW active counter나 CPU sched runtime과 동일하다고 해석하지 않는다.
- summary latency의 pairing은 수집자가 사용한 `correlation_id` 또는 `flow`를 명시한다. 표본 pairing의 실제 적절성은 원본 자료로 확인해야 한다.

## 2. .pftrace에서 sequence와 통계 추출

예제: [meta-trace.yaml](../../examples/measurement-import/profiling/meta-trace.yaml).

```powershell
uv run python -m scenario_db.meas_import.cli --meta capture/meta.yaml --out generated/profiling --strict
```

`task_mapping`은 slice 정규식, process/thread 이름·정규식, track 이름으로 canonical task/node를 연결한다. `execution_kind: hw`로 HW track을 지정한다. 이름은 실제 사내 trace에 맞게 수정한다.

`include_sequence: true`일 때 thread_track뿐 아니라 일반 track도 조회한다. event instance ID는 `slice:<id>`이고 logical task와 별도다. 절대 시각은 정수 ns로 유지하고 chart에는 공통 origin을 뺀 ms를 전달한다. 반복 task를 하나의 bar로 합치지 않는다.

latency는 Perfetto `flow.slice_out -> slice_in`으로 연결된 쌍에서 산출한다. 기본값은 `successor.start - predecessor.end`; `source_anchor: start`도 추출할 수 있다. 단순 timestamp 정렬은 causal edge로 변환하지 않는다. 음수 end-to-start 간격, 중복 mapping, required task의 표본 누락, required latency의 flow 누락은 오류다. 다중 선행 event가 있으면 실제 flow별 통계를 집계한다. loop/frame별 correlation 해석은 trace producer의 flow가 정확해야 한다.

`required: true`이면 trace 누락, Perfetto 미설치, `--skip-perfetto`를 통한 생략도 실패한다. 완료되지 않은 slice(dur < 0)는 집계에서 제외된다. frame marker는 기존 count_per_frame 계산에만 쓰인다. 현재 frame/stream 자동 식별과 잘린 sample별 품질 보고서는 구현하지 않았다.

추출 trace의 hash·크기와 import fingerprint를 보존한다. 원본 trace binary는 YAML/DB에 넣지 않는다. Measurement 화면의 SW timing 탭에서 HW 표·SW latency 표·측정 timing chart를 확인할 수 있다.

## 3. 반복 업데이트와 재현성

같은 evidence ID에 다른 내용이 있으면 CLI와 profiling ETL은 덮어쓰기를 거부한다. 새 capture는 새 ID로 만든다. 동일 파일의 재실행은 idempotent하다. metadata를 수정한 경우에도 새 revision ID를 사용한다. fingerprint는 출처 추적용이며 다른 내용의 덮어쓰기 권한이 아니다.

측정 YAML은 기존 ETL 경로로 적재한다. trace와 summary에서 같은 timing 그룹을 동시에 공급하면 조용히 우선순위를 적용하지 않고 오류로 처리한다.

## 4. 측정 profile을 시뮬레이션에 적용

다음 selection YAML을 준비한다. `design_conditions`는 선택한 **resolved variant의 전체 값**을 복사한다. task_mapping의 오른쪽은 시뮬레이터에 존재하는 task/node ID다.

```yaml
profile_id: camera-capture-r1
revision: 1
statistic: mean
# 아래 {}는 placeholder다. 실제 variant의 전체 조건으로 교체한다.
design_conditions: {}
task_mapping:
  eis: eis
```

```powershell
uv run python -m scenario_db.meas_import.timing_profile --evidence generated/profiling/03_evidence/meas-capture-r1.yaml --selection selection.yaml --out generated/profiling/timing-profile-r1.yaml
```

생성된 전체 profile을 기존 `POST /api/v1/simulation/run` 요청의 `config.timing_profile`에 넣는다. 측정 evidence를 먼저 DB에 적재해야 한다. profile의 evidence hash는 해당 YAML 파일 hash다. API는 project/scenario/variant, 원본 hash, silicon revision, SW baseline, thermal, power state를 확인한다. profile의 design_conditions도 정확히 일치해야 한다. DVFS override와 inline DVFS table을 통한 외삽은 거부한다. 제공된 ambient temperature·DVFS selector·SW runtime override도 비교한다. 전체 IP catalog revision fingerprint 및 capture 중 OPP residency의 호환성 검증은 후속 작업이므로 이 profile을 다른 HW revision에 재사용하지 않는다.

profile은 scenario를 변경하지 않고 timeline duration/해당 edge delay를 대체한다. min/mean/max는 입력 사례 선택이며 전체 pipeline의 통계적 percentile 예측이 아니다. 동일 profile에 포함된 SW stage의 HW budget도 선택한 runtime에 맞게 계산한다. wall runtime을 CPU energy로 변환하지 않는다.

run_info에 profile 내용과 revision을 저장하고, derived_from으로 측정 evidence를 연결한다. profile은 cache hash에 포함된다. 이전 revision을 다시 선택하면 rollback할 수 있다. 기본 profile pointer 자동 전환, 부분 patch UI, A/B frame 정렬은 후속 작업이다. 측정 profile 선택·다운로드 UI는 아래 후속 구현 절을 참조한다.

## 5. 기존 scenario에서 탐색

`POST /api/v1/exploration/scenarios/preview`:

```json
{
  "project_ref": "proj-sm-s947b",
  "scenario_id": "uc-camera-recording",
  "variant_id": "cam-rec-r1-fhd30-vdis",
  "axes": [{"target": "sw_margin", "values": [1.1, 1.2]}],
  "include_results": false
}
```

지원 축은 `sw_margin`과 `node_clock_mhz`다. 후자는 node_id가 필요하다. 기존 variant 상속을 먼저 해석하고 baseline + OFAT 사례를 독립 복사해 실행한다. baseline을 포함해 기본 최대 500개, 기존 request 크기·동시 실행·timeline frame 제한을 적용한다. evidence나 variant를 저장하지 않는다. 각 사례의 input_hash와 baseline delta를 반환한다.

전력 누락 domain이 있으면 전체 전력은 null, 모델링한 부분 합은 known_power_mw, optimization_eligible은 false다. area/LLC traffic/OTF 연결/PPC 세대 변경을 이 API로 지원한다고 해석하면 안 된다. 실행 가능한 해당 축을 추가한 뒤 계약을 확장해야 한다.

## 6. 참조 fixture와 정식 fixture의 경계

`capabilities.bw_model/dvfs_model/power_model/perf_model/sw_task_model`과 `platform_model`은 출처 envelope로 보존한다. 내부 formula 문자열은 실행하지 않는다. 이 데이터가 있다는 이유만으로 readiness의 PPC 요건이나 모델 검증을 통과시키지 않는다. devfreq의 min/max 정보는 완전한 OPP 테이블이 아니다.

`parametric_sweeps`, scenario provenance, platform metadata가 DB에 저장된다. 기존 scenario write/export 경로에서도 sweep/provenance를 보존한다. 운영 모드 max_clock_mhz는 시뮬레이션 상한과 더 작은 쪽으로 적용한다.

원본과 현행 fixture 비교:

```powershell
uv run python scripts/review_fixture_snapshot.py --source <reference-directory> --current db_fixtures_Exynos2600_S26Plus --out <manifest.json>
```

manifest는 파일 hash, shared/changed ID, 현행에만 존재하는 variant를 기록한다. source와 current에는 쓰지 않는다.

2026-09-16 검증에서 원본 46개 파일의 schema 적재는 성공했으나 strict semantic ETL은 MTNR/MFC selected_mode 불일치 23건으로 실패했다. 원본 전체의 정식 승격은 아직 가능하지 않다. 원본 mode alias에 대한 확인 없이 catalog에 임의의 지원 모드를 추가하지 않는다. 현행 v15 fixture는 기존 strict ETL과 회귀 테스트로 별도 검증한다.

## 남은 계획

이 변경은 P0/P1 입력 보존과 P2 실측 경로, P3 clock 상한, P6 제한된 탐색의 구현이다. 계획 전체 P0~P9 완료가 아니다. 다음은 별도 구현·자료 검증이 필요하다.

- 사내 실제 .pftrace의 HW track/flow/correlation 매핑 인수, frame/stream/clock 품질 보고와 sample exclusion 사유.
- MFC/MSCL/ABOX/UFS typed throughput, DPU/MFC bandwidth vote와 physical traffic 분리, platform MIF/INT DVFS 소비.
- CPU active runtime·전압·계수 기반 energy와 전체 power coverage의 모든 기존 UI/비교 경로 적용.
- profile 승인·기본 pointer, partial update, A/B frame 정렬. 선택·다운로드 UI는 아래 후속 구현에서 지원한다.
- OTF topology/port/SRAM 검증, LLC capacity/traffic, area 비용, Pareto/차기 SoC 투영.
- MTNR/MFC 모드 불일치 해결 후 namespace 분리 staging 및 13 UC 전체 정식 승격.


## UI에서 측정 profile 준비·실행 (2026-09-16 후속 구현)

Evidence Dashboard의 Calculation 모드에서 scenario/variant를 선택하고 **Use measured timing profile**을 켠다.

1. Stored measurement에서 해당 scope의 capture를 선택한다. HW/SW timing 표와 capture context를 확인한다.
2. task → active node mapping을 편집하고 profile ID/revision, mean/min/max를 선택한다. node_id가 없는 SW task의 기본 mapping은 task 이름이며, 실제 node 이름과 다르면 사용자가 수정해야 한다.
3. Prepare measured profile을 누르면 DB measurement hash와 resolved baseline에서 profile을 준비한다. 새로운 `POST /evidence/{id}/timing-profile` API는 DB를 변경하지 않는다.
4. Download pinned profile로 보관하고 Run measured timing preview로 실행한다. 결과를 검토한 뒤 기존 Confirm & Save Evidence 흐름을 사용한다.
5. 이전 revision으로 되돌릴 때 Profile YAML을 선택해 보관한 profile을 업로드한다. 다른 scenario/variant의 파일은 거부한다.

새 API가 생성한 profile은 source_task_mapping과 baseline_sha256을 포함한다. 재실행 시 topology, size profile, resolved variant, project 설정, IP catalog, SoC metadata 변경을 검사한다. source task mapping이 있는 profile의 runtime/latency도 원본 측정값과 비교한다. 입력 YAML의 수치만 바꾸어 measured 값으로 재사용할 수 없다. 기존 CLI profile에 새 baseline hash가 없으면 이전 호환 동작을 유지하므로 DB 기반 준비 API 사용을 권장한다.

Replay는 capture의 실행 context를 사용하며 일반 form의 기본 thermal/inline DVFS table을 섞지 않는다. FPS 외삽은 거부한다. active runtime은 wall duration으로 대체하지 않는다. min_ms 또는 samples가 없는 기존 measurement는 해당 task의 누락 필드를 보완한 새 capture revision이 필요하다.

이 UI는 명시적 profile 선택과 파일 revision 복구를 제공한다. 중앙 profile registry, 승인 workflow, 자동 default pointer, 부분 patch는 여전히 후속 범위다.
