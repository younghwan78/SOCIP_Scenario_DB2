# 예측-실측 비교 운영 가이드

이 문서는 camera recording scenario의 예측(`evidence.simulation`)과 실측
(`evidence.measurement`)을 ScenarioDB에 넣고 차이를 확인하는 실무 절차다.
첫 적용 대상은 FHD30, FHD60, UHD30, UHD60, 8K30 recording variant다.

저장소의 예시와 테스트 데이터는 합성 데이터만 사용한다. 실제 과제 ID, 장비 ID,
원본 로그, 사내 저장소 경로, 계정과 인증 정보는 사내 환경에서만 설정한다.

## 1. 적용 전 결정할 항목

먼저 다섯 variant가 같은 scenario 아래에서 구분되도록 사내 canonical ID를 확정한다.
아래 이름은 예시일 뿐이며 기존 사내 명명 규칙이 있으면 그 규칙을 우선한다.

| 촬영 모드 | variant 예시 |
|---|---|
| FHD 30 fps | `cam-rec-fhd30` |
| FHD 60 fps | `cam-rec-fhd60` |
| UHD 30 fps | `cam-rec-uhd30` |
| UHD 60 fps | `cam-rec-uhd60` |
| 8K 30 fps | `cam-rec-8k30` |

비교 전 다음 값도 고정해야 한다.

- `project_ref`, `scenario_ref`, `variant_ref`
- `execution_context.sw_baseline_ref`, `thermal`, `power_state`
- rail, DMA port, pipeline stage, SW task/thread의 논리 이름
- 각 로그 값의 단위와 통계 의미(mean, p95, 반복 횟수)
- runtime과 runtime/start jitter의 시작점·종료점 정의

논리 이름은 예측과 실측의 join key다. 원본 thread 이름이나 빌드마다 달라지는
process ID를 그대로 쓰지 않는다.

## 2. 측정값을 canonical metric에 매핑하기

상세 metric의 식별자는 다음 세 값의 조합이다.

```text
metric_id + scope.kind + scope.ref
```

현재 기본 catalog는
`src/scenario_db/models/evidence/metric_catalog.yaml`에 있다.

| 측정 항목 | metric | scope | canonical unit | 비교에 쓰는 실측 통계 |
|---|---|---|---|---|
| 전체 전력 | `power.total` | `scenario:self` | `mW` | mean |
| rail 전력 | `power.rail` | `rail:<rail>` | `mW` | mean |
| rail 전압 | `power.rail_voltage` | `rail:<rail>` | `V` | mean |
| rail 전류 | `power.rail_current` | `rail:<rail>` | `mA` | mean |
| 전체 BW | `bandwidth.total` | `scenario:self` | `MB/s` | mean |
| read/write/OTF BW | `bandwidth.read/write/otf` | `dma_port:<node:port>` 또는 `ip:<ip>` | `MB/s` | p95 |
| frame latency | `latency.frame` | `scenario:self` | `ms` | p95 |
| stage latency | `latency.stage` | `pipeline_stage:<stage>` 또는 `ip:<ip>` | `ms` | p95 |
| 유효 FPS | `camera.fps` | `scenario:self` | `fps` | mean |
| frame drop | `camera.frame_drop` | `scenario:self` | `count` | value |
| SW runtime | `sw.runtime` | `task:<task>` 또는 `thread:<thread>` | `ms` | p95 |
| runtime jitter | `sw.runtime_jitter` | `task:<task>` 또는 `thread:<thread>` | `us` | p95 |
| start jitter | `sw.start_jitter` | `task:<task>` 또는 `thread:<thread>` | `us` | p95 |
| deadline miss | `sw.deadline_miss` | `task:<task>` 또는 `thread:<thread>` | `count` | value |

전체 전력, 전체 BW, frame latency, FPS, frame drop은 headline query도 가능하도록
`kpi`에 유지한다. Rail/task/stage처럼 범위가 있는 값은
`metric_observations`에 넣는다. 새로운 측정 필드가 생기면 top-level 필드를
늘리기보다 catalog entry와 observation을 추가하는 것이 기본 원칙이다.

기존 metric의 의미나 canonical unit는 제자리에서 바꾸지 않는다. 단위 변환은
import adapter에서 끝내고 비교 엔진에는 canonical unit만 전달한다.

## 3. 가장 작은 실측 입력 만들기

원본 로그 adapter가 아직 없으면 `meta.yaml`에 집계값을 직접 넣어 시작할 수 있다.
다음 예시는 공개 가능한 합성 데이터다.

```yaml
schema_version: "2.2"
project_ref: proj-demo-camera
scenario_ref: uc-camera-recording
variant_ref: cam-rec-fhd30
measured_at: "2026-07-30T10:00:00+09:00"
execution_context:
  silicon_rev: EVT1
  sw_baseline_ref: sw-demo-v1.0
  thermal: room
  power_state: discharging
  method: measurement
provenance:
  collection_method: synthetic-guide
  sample_count: 10
kpi:
  total_power_mw: {mean: 3850, p95: 4010, n: 10}
  total_bw_mbs: {mean: 6225, p95: 6410, n: 10}
  frame_latency_ms: {mean: 28.4, p95: 32.1, n: 5400}
  fps_effective: {mean: 29.97, p95: 30.01, n: 5400}
metric_observations:
  - metric_id: power.rail_voltage
    scope: {kind: rail, ref: VDD_CAM}
    unit: V
    stats: {mean: 0.75, p95: 0.76, n: 10}
  - metric_id: power.rail_current
    scope: {kind: rail, ref: VDD_CAM}
    unit: mA
    stats: {mean: 1306, p95: 1410, n: 10}
  - metric_id: power.rail
    scope: {kind: rail, ref: VDD_CAM}
    unit: mW
    stats: {mean: 980, p95: 1080, n: 10}
  - metric_id: bandwidth.read
    scope: {kind: dma_port, ref: isp0:RDMA0}
    unit: MB/s
    stats: {mean: 1320, p95: 1420, n: 5400}
  - metric_id: latency.stage
    scope: {kind: pipeline_stage, ref: eis_warp}
    unit: ms
    stats: {mean: 7.8, p95: 10.6, n: 5400}
  - metric_id: sw.runtime
    scope: {kind: task, ref: eis_warp}
    unit: ms
    stats: {mean: 7.8, p95: 10.6, max: 13.2, n: 5400}
  - metric_id: sw.start_jitter
    scope: {kind: task, ref: eis_warp}
    unit: us
    stats: {mean: 84, p95: 210, max: 620, n: 5400}
```

`kpi`나 `metric_observations` 중 하나만 있어도 import할 수 있다. 같은 identity가
원본 digest와 명시 observation 양쪽에서 생성되면 명시 observation이 우선한다.

## 4. 원본 power와 Perfetto를 함께 쓰기

Rail별 voltage/current/power 반복 측정 CSV는 `rail_long` 형식으로 연결한다.

```yaml
power:
  csv: power_monitor.csv
  format: rail_long
  run_column: run
  rail_column: rail
  voltage_column: voltage_v
  current_column: current_ma
  power_column: power_mw
```

Importer가 rail별 `power.rail`, `power.rail_voltage`,
`power.rail_current` observation을 생성한다.

Perfetto에서는 raw process/thread 이름을 논리 task로 매핑한다.

```yaml
perfetto:
  trace: trace.pb
  frame_slice_name: "Camera::ProcessFrame"
  task_mapping:
    - task: eis_warp
      cluster: BIG
      match: {process: "vendor.camera.provider", thread_re: "VDIS.*"}
```

사내 BW/camera 로그 형식이 확정되면 별도 source adapter를 작성하되 출력은 같은
canonical `meta.yaml`/measurement contract로 끝나야 한다. 비교 API가 raw 로그를
직접 해석하게 만들지 않는다.

## 5. Import와 적재

저장소 root에서 아래 명령을 실행한다.

```powershell
cd <SCENARIODB_ROOT>

.\.venv\Scripts\python.exe -m scenario_db.meas_import.cli `
  --meta path\to\meta.yaml `
  --out generated\measurements `
  --strict `
  --fail-on-warning
```

성공 조건은 프로세스 종료 코드가 0이고
`generated\measurements\meas_import_report.json`의 `ok`가 `true`인 것이다.
warning을 허용해야 하는 사유가 명확하지 않다면 `--fail-on-warning`을 유지한다.

DB migration과 strict ETL을 실행한다.

```powershell
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:15432/scenario_db"

uv run alembic upgrade head

.\.venv\Scripts\python.exe -m scenario_db.etl.loader `
  generated\measurements\03_evidence `
  --strict `
  --report-json generated\measurements\etl-report.json
```

`etl-report.json`의 `ok=true`, skipped/error 0을 확인한다. 예측 evidence도 동일한
project/scenario/variant와 비교 가능한 execution context로 적재되어 있어야 한다.

## 6. API로 비교하기

API를 실행한 뒤 prediction/measurement evidence ID를 지정한다.

```powershell
$predictionId = [uri]::EscapeDataString("sim-camera-fhd30-prediction")
$measurementId = [uri]::EscapeDataString("meas-camera-fhd30-EVT1-20260730T100000")
$uri = "http://127.0.0.1:18000/api/v1/compare/prediction-measurement?prediction_id=$predictionId&measurement_id=$measurementId"

$result = Invoke-RestMethod -Method Get -Uri $uri
$result.context
$result.summary
$result.rows | Format-Table metric_id, scope_kind, scope_ref, prediction, measurement, delta_pct, status
```

Delta의 정의는 항상 다음과 같다.

```text
delta = prediction - measurement
delta_pct = delta / measurement * 100
```

`polarity`는 metric의 좋고 나쁨을 해석하기 위한 정보이고 delta 부호 자체를 뒤집지는
않는다. 예를 들어 lower-is-better metric에서 양수 delta는 예측값이 실측보다 큰
상태다.

## 7. Dashboard에서 확인하기

```powershell
uv run --group dashboard streamlit run dashboard\Home.py `
  --server.port 18502 `
  --server.address 127.0.0.1
```

Dashboard의 `Evidence Dashboard`에서 다음 순서로 확인한다.

1. project, camera recording scenario, variant를 선택한다.
2. measurement evidence를 선택한다.
3. `Overview`에서 headline KPI를 확인한다.
4. `Power`, `SW Timing`, `Metrics`에서 rail/task/scoped metric을 확인한다.
5. `Prediction vs Measurement`에서 대응 prediction을 선택한다.
6. context와 coverage summary를 먼저 보고 metric별 delta를 확인한다.

`Metrics`는 범용 비교 표이고 `Power`와 `SW Timing`은 전문 상세 표다. 둘 중 하나를
대체하는 관계가 아니다.

## 8. 비교 status 해석

| status | 의미 | 조치 |
|---|---|---|
| `MATCHED` | identity, unit, 필요한 통계와 context가 비교 가능 | delta와 원본 evidence를 검토 |
| `PREDICTION_ONLY` | 예측에만 metric이 있음 | 실측 adapter 누락 또는 의도적 미측정인지 확인 |
| `MEASUREMENT_ONLY` | 실측에만 metric이 있음 | 예측 모델/출력 coverage를 확인 |
| `UNIT_MISMATCH` | 양쪽 unit가 다름 | source adapter에서 canonical unit로 정규화 |
| `STATISTIC_MISSING` | catalog가 요구한 mean/p95/value가 없음 | 측정 집계 또는 catalog 정의를 확인 |
| `CONTEXT_MISMATCH` | 비교를 막는 identity/context 차이가 있음 | 잘못 연결된 evidence를 수정하고 재적재 |

누락 metric은 0으로 간주하지 않는다. `*_ONLY`는 예측 또는 실측 coverage 부족을
드러내는 정상적인 결과다.

다음 mismatch는 delta 계산을 막는다.

- project, scenario, variant
- SW baseline, thermal state, power state

Silicon revision과 ambient temperature 차이는 pre-silicon 예측과 실제 silicon을
비교할 수 있도록 advisory다. 하지만 결과 해석 시 차이를 반드시 기록한다.

## 9. 새로운 metric을 추가할 때

필드가 늘어날 때는 다음 순서를 따른다.

1. 측정 대상과 시작점·종료점, aggregation, 단위를 문서로 정의한다.
2. `metric_catalog.yaml`에 새 `metric_id`, category, scope, canonical unit,
   compare statistic, polarity를 추가한다.
3. source adapter에서 원본 단위를 canonical unit로 변환한다.
4. 정상, 필수 열 누락, 단위 변환, 중복 sample, 불완전 run을 합성 fixture로 테스트한다.
5. simulation과 measurement 양쪽이 같은 logical scope ref를 내는지 확인한다.
6. strict import/ETL과 비교 API/Dashboard 회귀 테스트를 통과시킨다.

기존 metric의 의미를 바꿔야 한다면 새 metric ID를 만들고 저장된 evidence의
reconciliation 계획을 함께 세운다.

## 10. 다섯 camera variant 수용 체크리스트

각 variant마다 아래를 독립적으로 확인한다.

- [ ] prediction과 measurement의 project/scenario/variant가 일치한다.
- [ ] SW baseline, thermal, power state가 빠짐없이 기록되어 있다.
- [ ] total power, total BW, frame latency, effective FPS가 보인다.
- [ ] 기대한 rail의 voltage/current/power identity가 모두 보인다.
- [ ] 기대한 DMA/path BW와 pipeline stage latency가 보인다.
- [ ] 주요 SW task runtime과 jitter가 논리 task 이름으로 보인다.
- [ ] unit/statistic mismatch가 0건이거나 사유와 조치가 기록되어 있다.
- [ ] prediction-only와 measurement-only 항목이 의도된 coverage 차이인지 검토했다.
- [ ] raw artifact pointer와 sha256가 사내 보관 정책에 맞는다.
- [ ] reviewer가 각 delta를 원본 evidence까지 추적할 수 있다.

처음에는 FHD30 한 variant를 vertical slice로 통과시킨 뒤 나머지 네 variant를
동일한 contract로 확장하는 방식을 권장한다.

## 11. 변경 후 검증 명령

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\meas_import `
  tests\unit\test_evidence_comparison.py `
  tests\unit\dashboard\test_measurement_result_view.py `
  -q

.\.venv\Scripts\python.exe -m ruff check src tests dashboard
.\.venv\Scripts\python.exe -m mypy src
git diff --check
```

DB schema나 API mapping을 바꿨다면 PostgreSQL이 실행 중인 상태에서 integration
test도 추가로 수행한다.

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\integration\test_api_evidence.py `
  tests\integration\test_alembic_schema_drift.py `
  -q
```

전체 contract는 다음 문서를 함께 참고한다.

- `docs/contracts/data/metric-observation-contract.md`
- `docs/contracts/data/measurement-evidence-contract.md`
- `docs/guides/measurement/measurement-import-guide-ko.md`
- `docs/guides/measurement/projection-guide-ko.md`
- `internal_docs/design_notes/measurement-comparison-design.md`
