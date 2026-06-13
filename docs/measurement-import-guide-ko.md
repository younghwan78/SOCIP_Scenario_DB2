# Measurement Import 가이드 (meas_import)

`scenario_db.meas_import`는 한 번의 측정 캡처(power monitor CSV + perfetto trace)와
`meta.yaml` 사이드카를 입력받아 canonical `evidence.measurement` YAML을 생성한다.
필드 의미와 3-tier 저장 정책은 `docs/measurement-evidence-contract.md`를 따른다.

## 1. 입력 구성

측정 1회분 = 디렉터리 하나:

```text
measurements/uhd30-vdis/
  meta.yaml            # 측정팀이 작성하는 사이드카 (유일한 수기 입력)
  power_monitor.csv    # rail별 전력 waveform
  trace.pb             # perfetto trace (선택, 대용량 — repo에 commit하지 않음)
```

측정팀이 채우는 것은 `meta.yaml`뿐이다. 나머지는 캡처 도구의 원본 산출물이다.

## 2. 데이터 흐름

```mermaid
flowchart LR
    META[meta.yaml] --> CLI
    CSV[power_monitor.csv] --> CLI
    TRACE[trace.pb] --> CLI
    CLI["meas_import.cli<br/>· power CSV 집계<br/>· perfetto digest 추출<br/>· artifact sha256<br/>· MeasurementEvidence 검증"]
    CLI --> Y["evidence.measurement YAML"]
    Y --> ETL["etl.loader / Write API"]
    ETL --> DB[(PostgreSQL)]
```

추출 로직은 raw 원본을 DB에 넣지 않는다. KPI(Tier1)와 digest(Tier2)만 DB로 가고,
원본(Tier3)은 파일 저장소에 두고 `artifacts`에 경로 + sha256만 기록한다.

## 3. 실행

```powershell
cd E:\50_Codex_Soc_Scenario_DB\implementation
uv run python -m scenario_db.meas_import.cli `
  --meta demo\measurements\uhd30-vdis\meta.yaml `
  --out generated\measurements `
  --strict
```

산출물:

```text
generated/measurements/
  03_evidence/
    meas-<scenario>-<variant>-<silicon_rev>-<YYYYMMDD>.yaml
  meas_import_report.json
```

플래그:

- `--skip-perfetto` — perfetto 섹션이 있어도 trace digest를 건너뛰고 power-only로 적재.
- `--strict` — error 발생 시 non-zero 종료.
- `--fail-on-warning` — `--strict`와 함께, warning도 실패로 처리.
- `--skip-generated-validation` — 생성 YAML의 MeasurementEvidence 검증 생략(비권장).

생성 후 DB 적재는 contract 문서의 적재 경로(direct ETL)를 따른다:

```powershell
uv run python -m scenario_db.etl.loader generated\measurements\03_evidence
```

## 4. meta.yaml 작성

### 4.1 식별/정적 메타

```yaml
schema_version: "2.2"
# id 생략 시 meas-<scenario>-<variant>-<silicon_rev>-<YYYYMMDD>로 자동 생성
project_ref: proj-sm-s947b
scenario_ref: uc-camera-recording
variant_ref: cam-rec-r1-uhd30-vdis
measured_at: "2026-06-10T15:20:00+09:00"   # ISO 8601
execution_context:
  silicon_rev: EVT1
  sw_baseline_ref: sw-vendor-v1.2.3
  thermal: room
  method: measurement                       # 생략 시 measurement로 강제
provenance:
  device_id: "EVT1-ERD-SN-0042"
  ...
```

### 4.2 추출기가 만들지 않는 KPI

frame latency, 유효 fps 등 측정 앱 로그에서 오는 값은 `kpi`로 직접 전달한다.

```yaml
kpi:
  frame_latency_ms: 28.4
  fps_effective: 29.97
```

`total_power_mw`를 `kpi`에 직접 적으면 power CSV 집계값보다 우선한다.

### 4.3 Power CSV 매핑 (`power`)

CSV는 time 열 + rail별 전력(mW) 열로 구성된 waveform이다. 각 rail은 캡처 구간 전체에
대해 mean/p95/std/n으로 집계된다(n = CSV 샘플 수).

```yaml
power:
  csv: power_monitor.csv          # meta.yaml 기준 상대경로 또는 절대경로
  time_column: timestamp_ms
  total_power_rails:              # 샘플별로 합산 후 집계 → total_power_mw KPI
    [VDD_CAM, VDD_MIF, VDD_INT, VDD_NPU, VDD_BIG, VDD_MID, VDD_LIT]
  # total_power_column: TOTAL     # 이미 합산된 열이 있으면 이걸 우선 사용
  rails:
    VDD_CAM: {role: vdd}                            # → vdd_power
    VDD_BIG: {role: cpu_cluster, cluster: BIG}      # → cpu_breakdown[BIG].power_mw
    VDD_MID: {role: cpu_cluster, cluster: MID}
    VDD_LIT: {role: cpu_cluster, cluster: LIT}
    # role: ignore — 집계 제외
```

- `role: vdd` → `vdd_power[rail] = {mean_mw, p95_mw}`.
- `role: cpu_cluster` → 같은 cluster의 rail을 **샘플별로 합산**한 뒤 MeasuredKpi로 집계해
  `cpu_breakdown[cluster].power_mw`에 들어간다.
- `total_power_rails`는 지정 rail을 **샘플별 합산** 후 집계한다(통계적으로 올바른 방식).

### 4.4 Perfetto digest (`perfetto`)

```yaml
perfetto:
  trace: trace.pb
  cpu_to_cluster:                 # perfetto CPU index → 논리 cluster
    0: LIT
    7: BIG
  frame_slice_name: "Camera::ProcessFrame"   # count_per_frame 정규화용 frame 수
  # frame_count: 5400             # 명시 지정 시 위 slice count 쿼리를 건너뜀
  task_mapping:
    - task: eis_warp              # 논리 task 이름 (raw thread name 아님)
      cluster: BIG
      match: {process: "vendor.camera.provider", thread_re: "VDIS.*"}
    - task: encoder_input_feed
      match: {process: "mediaserver", slice_re: "encodeFrame"}
```

추출 결과:

- `cpu_to_cluster` → cluster별 `freq_residency`(시간 가중) + `avg_freq_mhz` →
  `cpu_breakdown`에 병합.
- `task_mapping` → 매칭된 slice duration을 task별 mean/p50/p95/max/samples로 롤업하고,
  frame 수가 있으면 `count_per_frame`을 계산 → `sw_task_timing`.

`match`는 `process`/`process_re`/`thread`/`thread_re`/`slice_re` 중 하나 이상.
`*_re`는 정규식(부분 일치). **논리 task 이름은 프로젝트 간 SW projection의 join 키**이므로
U/V에서 같은 기능에 같은 이름을 써야 한다(contract 문서 §2 task naming 규약).

### 4.5 Artifacts

```yaml
artifacts:
  - type: perfetto_trace
    storage: fileshare
    path: "artifacts/proj-sm-s947b/uc-camera-recording/cam-rec-r1-uhd30-vdis/20260610-sw123/trace.pb"
    source: trace.pb              # sha256 계산용 로컬 파일 (생략 시 path 사용)
    mime: application/octet-stream
```

`source` 파일이 존재하면 sha256/bytes를 계산해 기록하고, 없으면 포인터만 남기고
warning을 낸다(원본이 파일 저장소에만 있고 변환 머신에 없는 경우가 정상).

## 5. perfetto 의존성

`perfetto` 패키지는 선택 의존성이며 lazy import된다.

- 설치되어 있고 trace 파일이 존재하면 trace_processor로 digest를 추출한다.
- 패키지가 없으면 `perfetto_unavailable` warning을 내고 power-only로 진행한다.
- trace 파일이 없으면 `perfetto_trace_not_found` warning 후 진행한다.

추출 로직(residency 정규화, percentile 롤업, task 매핑)은 `TraceQuery` 프로토콜에만
의존하므로 실제 binary 없이 단위 테스트된다(`tests/unit/meas_import/test_perfetto_digest.py`).
SQL은 `perfetto_digest.py` 상단 상수로 분리되어 trace config에 맞춰 검토/수정 가능하다.

## 6. 통계 의미

- 한 번의 캡처(단일 CSV) 내 시간 샘플들에 대한 mean/p95/std/n이다. `n`은 CSV 샘플 수.
- 반복 측정 회수는 `provenance.sample_count`로 별도 기록한다(현재 v1은 캡처당 CSV 1개).
- `ci_95`는 n>1이고 std>0일 때 정규근사 신뢰구간으로 계산된다.

## 7. 다음 단계와의 연결

- compare/추이 뷰: `/api/v1/evidence?kind=evidence.measurement&project_ref=...`로 조회,
  `/compare/*`로 sim vs meas / sw 버전별 비교(contract 문서 §6).
- U→V projection(Phase 5): U 측정으로 sim 보정 오차를 산출한 뒤 V projected evidence를
  `derived_from` lineage와 함께 생성한다.
