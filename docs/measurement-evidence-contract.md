# Measurement Evidence Contract

이 문서는 실측 데이터(`evidence.measurement`)를 ScenarioDB에 적재하기 위한 contract와,
프로젝트 간(U→V) 비교/projection을 위한 canonical scenario key 규약을 정의한다.

적용 버전: schema_version `2.2`, alembic revision `0011` 이후.

## 1. 데이터 계층 정책 (3-Tier)

측정 데이터는 세 계층으로 나누어 저장한다. 원본은 DB에 넣지 않는다.

| Tier | 내용 | 저장 위치 |
| --- | --- | --- |
| 1. KPI | `total_power_mw`, `frame_latency_ms` 등 비교/게이트용 대표값. 통계형(`mean/p95/std/ci_95/n`) 권장 | `evidence.kpi` (JSONB) |
| 2. Digest | cluster별 power/freq residency, SW task 수행시간 분포, rail별 전력, frame 이벤트 | `cpu_breakdown`, `sw_task_timing`, `vdd_power`, `timeline_events` (JSONB) |
| 3. Raw Artifact | perfetto trace, power monitor CSV, simpleperf data 원본 | 파일 저장소. DB에는 `artifacts`에 경로 + sha256만 기록 |

분석·비교·projection은 전부 Tier 1/2로 수행한다. Tier 3은 digest 재추출용 보험이다.

### Artifact 경로 규약

```text
artifacts/{project_id}/{scenario_id}/{variant_id}/{YYYYMMDD}-{sw_build}/
  trace.pb
  power_monitor.csv
  ...
```

- `artifacts[].storage`: 저장소 종류 (`fileshare`, `local`, 추후 `s3` 등).
- `artifacts[].path`: 저장소 root 기준 상대 경로.
- `artifacts[].sha256`: 필수 권장. 재추출 시 원본 무결성 확인에 사용.
- `provenance.raw_artifacts`는 하위 호환용으로 유지하되, 신규 데이터는 top-level
  `artifacts`를 사용한다.

## 2. evidence.measurement 필드 Contract

기존 필드(`provenance`, `aggregation`, `kpi`)에 더해 다음이 추가되었다.

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| `project_ref` | DocumentId, optional | 측정이 수행된 project/board. 프로젝트 간 비교 쿼리의 필터 키 |
| `measured_at` | ISO 8601 str | 측정 시각. "같은 variant의 최신 측정" 질의의 기준. DB에는 timestamptz로 저장 |
| `derived_from` | list[DocumentId] | lineage. 재집계/파생 evidence일 때 원본 evidence id 목록 |
| `execution_context.method` | `measurement` \| `calculation` \| `projection` | 값 산출 방식. measurement 문서는 `measurement` 고정 |
| `cpu_breakdown` | list | cluster별 digest. 아래 참조 |
| `sw_task_timing` | list | perfetto 기반 task별 수행시간 digest. 아래 참조 |
| `vdd_power` | dict[rail][metric] | rail별 전력. sim의 `vdd_power`와 같은 컬럼을 공유하므로 rail 이름을 sim fixture와 일치시킬 것 |
| `timeline_events` | list[dict] | frame drop 등 이벤트 digest. 자유 스키마(초기) |
| `artifacts` | list[Artifact] | 원본 포인터. §1 참조 |

### cpu_breakdown

```yaml
cpu_breakdown:
  - cluster: BIG                # LIT / MID / BIG — project 내에서 일관된 명칭 사용
    power_mw: {mean: 820.0, p95: 910.0, std: 38.0, n: 10}   # 또는 flat float
    avg_freq_mhz: 2210.0
    util_pct: 43.5
    freq_residency:             # perfetto cpu_frequency digest
      - {freq_mhz: 2600.0, ratio: 0.18}
      - {freq_mhz: 2210.0, ratio: 0.52, time_ms: 93600.0}
```

### sw_task_timing

```yaml
sw_task_timing:
  - task: eis_warp              # 논리 task 이름 — 아래 task naming 규약 참조
    process: vendor.camera.provider
    thread: EISCore0
    cluster: BIG                # 지배적 실행 cluster
    mean_ms: 6.4
    p50_ms: 6.1
    p95_ms: 8.9
    max_ms: 12.3
    count_per_frame: 1.0
    samples: 5400
```

Task naming 규약:

- `task`는 perfetto의 raw thread name이 아니라 **논리 task 이름**이다
  (`eis_warp`, `depth_npu`, `bokeh_gpu`, `hal_request_thread` 등).
- raw process/thread name → 논리 task 매핑 규칙은 project metadata에 저장하고,
  추출기(meas_import)가 이를 참조한다. SoC/SW 버전이 바뀌면 매핑만 갱신한다.
- 프로젝트 간 SW projection은 이 논리 task 이름으로 join하므로,
  U/V 프로젝트에서 같은 기능은 같은 task 이름을 써야 한다.

## 3. Method와 Lineage 규약

| method | kind | derived_from | 용도 |
| --- | --- | --- | --- |
| `measurement` | evidence.measurement | 보통 빈 값 | 실측 |
| `calculation` | evidence.simulation | 빈 값 | 현행 calculation 기반 sim |
| `projection` | evidence.simulation | **필수** — 근거가 된 측정/sim evidence id | 타 프로젝트 실측 기반 예측 |

규칙:

- `projection` evidence는 `derived_from`에 원본 measurement evidence id를 반드시 기록한다.
  lineage가 없는 projection은 review gate에서 신뢰할 수 없는 데이터로 취급해야 한다.
- projection의 보정계수/산식은 `calculation_trace.projection`에 기록한다(보정 detail,
  스케일된 항목, cluster_scaling, verify 시 error_report).
- projected sim은 HW 전력(계산값 × 보정계수)과 SW 시간(타 과제 실측 × cluster scale)을
  함께 담는다. 이를 위해 `evidence.simulation`에도 `sw_task_timing` 필드가 있다(native
  계산 run은 비워 둠).
- 생성/검증 도구와 recipe 작성은 `docs/projection-guide-ko.md`(`scenario_db.projection`)
  참조.

## 4. Canonical Scenario Key 규약 (프로젝트 간 비교)

### 문제

`scenarios.id`는 전역 PK이고 ETL은 scenario id의 project 간 충돌을 기본 거부한다
(`scenario_project_collision_policy`). 따라서 **Project U와 V는 같은
`uc-camera-recording` id를 가질 수 없다.**

### 규약

1. scenario id는 project-scoped로 작성한다. 예:
   - Project U: `uc-camera-recording-u`
   - Project V: `uc-camera-recording-v`
2. 프로젝트 간 매칭 키는 `metadata.canonical_usecase`에 기록한다:

   ```yaml
   id: uc-camera-recording-u
   project_ref: proj-u-...
   metadata:
     name: Camera Recording
     canonical_usecase: camera-recording   # U/V 동일 값
   ```

3. variant 매칭은 variant id 문자열이 아니라 `design_conditions`의 의미 키로 한다.
   최소 매칭 축: `subscenario`, `resolution`, `fps`, `sensor_place`, `hdr`.
   variant 명명이 프로젝트마다 달라도 matching이 깨지지 않는다.
4. evidence는 `project_ref` 컬럼으로 project를 직접 가리킨다
   (scenario join 없이 프로젝트 필터 가능).

### 비교/Projection 쿼리 모델

```text
U 실측  : canonical_usecase + design_conditions 키 + project_ref=U + kind=measurement
V 예측  : canonical_usecase + design_conditions 키 + project_ref=V + kind=simulation(method=projection)
V 실측  : (실리콘 도착 후) project_ref=V + kind=measurement → projected vs measured 오차 검증
```

## 5. 적재 경로

현재 지원되는 경로는 direct ETL이다:

```powershell
uv run python -m scenario_db.etl.loader <fixtures-dir>
```

- Write API staging(`scenario.import_bundle`)은 아직 `evidence.*`를 지원하지 않는다.
  측정 적재가 다인원 루틴이 되는 시점에 확장한다 (Phase 4+ 결정 사항).
- 같은 id로 재적재 시 `yaml_sha256`이 같으면 skip, 다르면 upsert된다.
  측정 데이터는 원칙적으로 append-only로 운용한다 — 새 측정은 새 id
  (`meas-...-{YYYYMMDD}` suffix)로 작성한다.

## 6. 조회 API

- `GET /api/v1/evidence?kind=evidence.measurement&project_ref=...&scenario_ref=...&variant_ref=...`
- `EvidenceResponse`에 `project_ref`, `measured_at`, `derived_from`,
  `cpu_breakdown`, `sw_task_timing`이 포함된다.
- `/compare/evidence`, `/compare/variants`는 `kind`, `project_ref` 필터를 받고,
  후보가 여럿이면 `measured_at` 최신(NULL은 후순위, 동률이면 id 역순)을 선택한다.
  `/compare/variants`는 ref의 scenario_id를 필터에 사용한다.

## 7. 예시 문서

전체 예시는 다음 fixture를 참조:

- `tests/unit/fixtures/evidence/meas-camera-recording-UHD60-EVT0-sw123.yaml`
- `demo/fixtures/03_evidence/meas-UHD60-EVT0-sw123.yaml`
