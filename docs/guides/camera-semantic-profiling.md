# Camera semantic profiling: import와 SW projection

Status: Current · Verified: 2026-09-17

사내 generator가 정제한 sequence와 통계를 받는다. 원본 raw trace parsing은 generator의 책임이다. RT/NRT HW 실측은 검증용이고, SW runtime과 edge gap은 명시적으로 선택하여 다른 variant/SoC에 projection한다. 예제 수치는 모두 합성값이다.

## 입력 준비

[실행 가능한 MD 예제](../../examples/measurement-import/camera/scenario-statistics.md)를 복사해 사용한다. 정확히 하나의 `yaml camera-profile-v1` fenced block이 필요하다. 일반 MD 표는 기계 입력이 아니다.

- `execution_context`: 기존 DB 계약의 silicon_rev, sw_baseline_ref, thermal. sw_baseline_ref는 등록된 `sw_profiles.id`이다. 개발 build 문자열을 자유롭게 넣는 필드가 아니다.
- `project_ref`, `scenario_ref`, `variant_ref`, timezone 포함 `measured_at`.
- `generator_version`, `measurement_scope`, `workload`: workload key/value는 선택한 variant의 design_conditions와 일치해야 한다. 기존 variant에 width/height가 없으면 이를 임의로 보내지 말고 실제 조건 key를 사용한다.
- `execution_path`: 경로 설명과 enabled_task_ids. task 이름이 아닌 안정적인 ID를 사용한다. 비활성 task를 기록하면 해당 canonical variant에서도 비활성이어야 한다.
- `pipeline_model.tasks/edges`: 논리 task와 canonical node_refs. 생략된 task는 정제 범위 밖일 수 있다. 전체 시스템에서 비활성이라고 해석하지 않는다.
- `statistics`: sw_task_timing, hw_task_timing(선택), sw_event_latency, stage_timing(선택).
- min_ms/mean_ms/max_ms/samples. 입력 경계에서 avg_ms를 mean_ms로 변환한다. 양수 count가 없으면 import 불가. 값을 추정해 채우지 않는다.
- RT/NRT group span은 stage_timing, 개별 HW는 hw_task_timing. SW의 timing_scope는 exclusive_sw 또는 inclusive_stage. exclusive_sw는 elapsed time이며 CPU active time이 아니다.

초기 설계의 단독 sw_baseline_ref 예시 대신 실행 가능한 계약은 execution_context 객체를 사용한다. JSONB 추가 필드에는 별도의 camera-profile-v1 producer version이 있다. 기존 evidence schema_version 2.2와 legacy import는 유지한다.

## DB와 UI

```powershell
uv run alembic upgrade head
```

Migration 0018: evidence.execution_path_id(TEXT), pipeline_model(JSONB), stage_timing(JSONB), profiling_metadata(JSONB). 기존 row는 NULL을 유지한다. 기존 SW/HW/latency 컬럼은 재사용한다.

Streamlit `Camera Profiling` → `Import / Review`에서 MD를 올리고 Preview, Save를 실행한다. preview는 DB를 변경하지 않는다. Save는 writer/admin, preview와 projection은 analyst/writer/admin 권한이 필요하다. 저장 전에 canonical project/variant/node, workload와 SW baseline을 확인한다.

기존 Evidence Dashboard에도 semantic graph, stage 통계와 edge gap이 표시된다. `GET /api/v1/evidence?execution_path_id=...`로 경로별 조회할 수 있다.

## 선택적 semantic trace

MD에 `semantic_trace: semantic.pftrace`를 추가하고 같은 bundle 디렉터리에 파일을 둔다. 기본 규격은 slice 이름이 logical task_id와 정확히 같다. Scenario track의 `~EIS fxxxx` 같은 이름은 task별 `trace_slice_name`과 `trace_track_name`으로 매핑할 수 있다. [15초 UHD30 EIS fixture와 확장 방법](../../examples/measurement-import/camera/uhd30-eis/README.md)을 참조한다. `observation_only: true`인 SW는 canonical node 없이 저장·표시할 수 있으나 projection에서는 거부한다.

```powershell
uv run python -m scenario_db.meas_import.camera --markdown capture/scenario-statistics.md --out generated/camera/evidence.yaml --trace-window-start-ms 0 --trace-window-ms 100
```

기본 CLI는 canonical evidence 파일만 생성한다. `--commit`을 추가하면 실행 중인 API의 preview → hash 확인 → commit을 거쳐 DB에 적재한다. 직접 SQL로 검증을 우회하지 않는다.

```powershell
uv run python -m scenario_db.meas_import.camera --markdown capture/scenario-statistics.md --commit --api-base http://127.0.0.1:18000/api/v1
```

- `--commit` 사용 시 `--out`은 선택이다. 함께 지정하면 로컬 YAML도 생성한다. 파일은 서버 model binding 전의 원본 정규화 결과이며, stdout의 hash는 DB에 저장된 결과를 가리킨다.
- 인증은 `SCENARIODB_API_KEY_ID`, `SCENARIODB_API_KEY` 환경변수에 설정한 writer/admin 계정을 사용한다. Secret을 명령행 옵션에 넣지 않는다. API 프로세스 환경은 CLI shell로 자동 전달되지 않는다.
- API 주소 기본값은 `SCENARIODB_API_BASE`, 미설정 시 `http://127.0.0.1:18000/api/v1`이다.
- 성공은 종료 코드 0과 JSON `persisted: true`, `status: created` 또는 `unchanged`로 표시한다. 인증·검증·연결·충돌 오류는 종료 코드 1이다.
- 같은 ID/같은 데이터 재실행은 no-op이다. 변경된 내용은 새 evidence ID가 필요하다. Commit 응답을 못 받은 경우 성공을 가정하지 않고, 동일 입력을 다시 실행해 저장 여부를 확인한다. 자동 재시도는 하지 않는다.
- 로컬 YAML 생성 후 API 저장이 실패하면 YAML은 남아 있지만 DB 저장 성공으로 보고하지 않는다.

생성 YAML을 Camera Profiling 화면에 올려 preview/저장하는 흐름도 유지한다. 서버는 입력 파일 경로를 직접 읽지 않는다. MD만 API로 업로드하면 trace를 읽지 않았다는 경고가 표시된다. CLI `--commit`은 로컬에서 추출한 semantic trace preview까지 함께 전송한다.

TraceProcessor가 필요한 경우 profiling extra를 설치한다. 파일은 bundle 디렉터리 안에 있어야 한다. 기본 trace origin부터 100ms 구간의 완전한 slice만 읽으며 최대 2,000 events, 최대 window 10초이다. 잘린 task와 구간 외 task는 preview에 포함하지 않는다. trace sample count를 MD 통계에 반영하거나 MD 값을 덮어쓰지 않는다.

Flow가 있으면 선언된 edge와 비교한다. Flow가 없으면 instance causal link를 만들지 않는다. preview는 자동 선택된 대표 frame이 아닌 지정 시간창이다. 원본 binary는 DB에 넣지 않고 semantic artifact의 이름/hash/크기만 보존한다.

## API

- `POST /api/v1/profiling/import/preview`: `{markdown: "..."}` 또는 `{evidence: canonical_document}`. evidence, sha256, warnings, missing_sw_statistics 반환.
- `POST /api/v1/profiling/import/commit`: 동일 입력과 `expected_hash`. canonical 내용이나 현재 graph가 변경되면 재preview 필요. 한 transaction으로 저장한다.
- 동일 ID/동일 내용은 unchanged. 동일 ID/다른 내용은 충돌. 변경은 새 ID와 supersedes_evidence_ref를 사용한다.
- `POST /api/v1/profiling/sw-projection/prepare`: 아래 selection 입력. DB source hash와 target graph hash가 고정된 projection 반환.
- `GET /api/v1/profiling/stage-comparison?measurement_id=...&prediction_id=...`: 동일 scope의 per-frame node boundary span 비교. clock 등 조건 일치의 최종 승인은 하지 않으며 diagnostic_only/validated=false를 반환한다.

```json
{
  "source_evidence_ref": "meas-camera-semantic-example-r1",
  "target_project_ref": "proj-sm-s947b",
  "target_scenario_ref": "uc-camera-recording",
  "target_variant_ref": "cam-rec-r1-uhd30-vdis",
  "target_path_id": "uhd30-vdis",
  "task_mapping": {"eis": "eis"},
  "edge_mapping": {},
  "statistic": "mean",
  "runtime_overrides": {"eis": {"scale": 1.3}},
  "latency_overrides": {},
  "assumption_notes": "Synthetic example: unchanged EIS implementation with 30% elapsed-time increase"
}
```

## 적용과 탐색

Projection을 `SimulationRunConfig.sw_timing_projection`에 넣는다. 기존 timing_profile과 동시 사용 불가. `/simulation/run`과 `/exploration/scenarios/preview`는 DB evidence로 projection을 다시 구성해 값·hash·mapping을 검증한다. target SW baseline/context는 target 실행 요청이 선택한다. source context를 target 실측으로 가장하지 않는다.

target_path_id는 선택한 경로의 표시용 label이다. 실제 활성 topology는 target variant가 결정하고 target_enabled_node_ids와 fingerprint로 고정한다. label만 바꿔 EIS/GDC를 끄지 않는다. bypass/LME/DOF 선택은 기존 variant topology에 먼저 반영해야 한다.

현재 projection은 frame당 1회 실행하는 exclusive SW task와 same-frame end-to-start latency를 지원한다. HW/stage runtime, inclusive SW, mixed-path summary, start-to-start gap, frame offset, target에서 HW를 포함하는 aggregate SW stage는 거부한다. HW 포함 stage는 먼저 SW/HW로 분리해야 한다.

UI `SW Projection`에서 source/target, mapping, task별 scale 또는 delta_ms, latency 조정을 입력한다. Clock 후보는 기존 OFAT 탐색 API를 사용한다. 예: `[{"target":"node_clock_mhz","node_id":"gdc_m","values":[300,400]}]`. 각 후보는 target 모델로 HW time/BW/power를 다시 계산한다. source evidence는 변하지 않으며 결과는 projected/exploration_only로 표시한다.

한 번에 하나의 축을 바꾸는 제한된 후보 평가이며, 자동 다변수 최적화나 합법 OPP 전수 탐색을 구현한 것은 아니다. 해당 OPP/voltage table과 target HW 모델의 유효성은 사용자가 검토해야 한다. CPU active energy가 없으면 전체 power는 unknown이고 계산 가능한 power만 표시한다.

## 제한과 인수 확인

- 실제 사내 semantic.pftrace/MD의 형식과 의미는 아직 인수 검증하지 않았다. 합성 trace를 실제 TraceProcessor로 읽는 검증과 별개이다.
- 사내 parser가 slice ID, 통계 구간, SW/HW 분리를 확정해야 한다. 복잡한 자동 correlation을 추가하지 않았다.
- stage 비교는 per-IP 시간 합이 아닌 동일 frame의 첫 시작/마지막 종료 span이다. 모든 경계 node가 없으면 비교 불가. clock/model revision 조건이 별도 확인되지 않으면 모델 정확도 승인으로 사용하지 않는다.
- 모든 task의 max를 동시에 쓰는 것은 보수적 stress 조건이며 관측 worst frame이나 확률 보장이 아니다.
- 신규 semantic evidence는 legacy measured-profile endpoint에서 거부한다. HW 검증값을 override로 우회 사용하지 않도록 한다.
