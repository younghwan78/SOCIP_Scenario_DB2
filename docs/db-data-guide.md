# DB Data Guide

이 문서는 ScenarioDB에 실제 데이터를 넣기 전에, 어떤 데이터가 DB에 들어가야 하고 어떤 데이터가 Query, Viewer, Simulation, Review에 필요한지 정리한다.

현재 구현 기준이다.

- Canonical YAML direct ETL: `soc`, `ip`, `sw_profile`, `sw_component`, `project`, `scenario.usecase`, `evidence.simulation`, `evidence.measurement`, `decision.*` 적재 가능.
- Write API staging: `scenario.variant_overlay`, `scenario.pipeline_patch`, `scenario.import_bundle` 지원.
- `scenario.import_bundle` 적용 문서: `soc`, `soc.dvfs_table`, `ip`, `sw_profile`, `project`, `scenario.usecase`.
- Simulation API: `POST /api/v1/simulation/run`에서 `persist=true`이면 `evidence.simulation`을 DB에 저장.
- Exploration API: 기본적으로 DB에 저장하지 않고 canonical scenario/import bundle preview를 만든다.

## 1. Big Picture

ScenarioDB 데이터는 크게 다섯 층이다.

```text
Capability data
  SoC, IP catalog, sensor/display catalog, SW profile/component
        |
Definition data
  Project, base scenario pipeline, scenario variants
        |
Runtime/Evidence data
  simulation result, measurement result, KPI, artifacts
        |
Decision data
  issue, gate rule, waiver, review
        |
Write audit data
  staged write batch and write events
```

가장 먼저 채워야 하는 것은 `Capability + Definition`이다. 이 두 층이 있어야 DB Explorer, Architecture Query, Pipeline Viewer가 의미 있는 결과를 낸다.

`Evidence`는 KPI, 최신 SW baseline, feasibility, simulation overlay를 만들기 위해 필요하다. `Decision`은 issue matching, gate result, waiver/review 추적을 위해 필요하다. `Write audit`은 사람이 직접 쓰는 데이터가 아니라 Write API가 자동으로 남기는 이력이다.

## 2. Minimum Useful Dataset

첫 real-data pilot의 최소 세트는 다음 순서가 좋다.

1. `soc`: 대상 SoC 하나.
2. `ip`: SoC가 참조하는 IP catalog. Sensor와 display panel도 우선 `kind: ip`, `category: sensor/display`로 넣는다.
3. `sw_profile`: 기본 SW baseline 하나.
4. `project`: board/form-factor 단위. `metadata.soc_ref`, `metadata.board_type`, `metadata.default_sw_profile_ref`가 중요하다.
5. `scenario.usecase`: base scenario. `pipeline.nodes`, `pipeline.edges`, `pipeline.buffers`가 핵심이다.
6. `scenario.usecase.variants[]`: 실제 비교 대상 variant. `design_conditions`, `size_overrides`, `node_configs`, `buffer_overrides`, `routing_switch`가 핵심이다.
7. Optional but recommended: `evidence.simulation` 또는 Simulation API persisted result.
8. Optional for review flow: `decision.issue`, `decision.gate_rule`, `decision.waiver`, `decision.review`.

이 최소 세트가 있으면 다음 화면/기능이 동작한다.

| Feature | 최소 필요 데이터 |
| --- | --- |
| DB Explorer summary | `project`, `scenario.usecase`, `variants`, `soc`, `ip`, `sw_profile` |
| Scenario catalog | `project.metadata`, `scenario.metadata`, `pipeline`, `variants` |
| Variant matrix | `variants.design_conditions`, `routing_switch`, `node_configs`, `buffer_overrides` |
| Import health | `project.soc_ref`, `project.sensor_module_ref`, `project.display_module_ref`, `scenario.pipeline` 참조 무결성 |
| Pipeline Viewer | `scenario.pipeline`, `ip_catalog`, variant overlay fields |
| Architecture Query | project/scenario/variant/topology/buffer fields, optional latest evidence |
| Simulation readiness | `ip_catalog.capabilities.sim`, `variant.node_configs`, buffers, shapes, fps |
| Simulation overlay | persisted `evidence.simulation` |
| Issue matching/gate | `decision.issue`, `decision.gate_rule`, variant context |

## 3. Data Kind Reference

### 3.1 Capability Data

Capability data는 "이 SoC/board/SW가 무엇을 지원하는가"를 담는다.

| YAML kind | DB table | 필수 성격 | Query/Viewer에서 중요한 필드 |
| --- | --- | --- | --- |
| `soc` | `soc_platforms` | SoC identity와 포함 IP 목록 | `id`, `ips[].ref`, `process_node`, `memory_type`, `bus_protocol` |
| `soc.dvfs_table` | `soc_dvfs_tables` | SoC 기준 DVFS table version | `soc_ref`, `dvfs_version`, `evt_hint`, `domains` |
| `ip` | `ip_catalog` | HW IP, sensor, display, memory catalog | `id`, `category`, `hierarchy`, `capabilities`, `compatible_soc` |
| `sw_profile` | `sw_profiles` | SW baseline 묶음 | `metadata.baseline_family`, `metadata.version`, `feature_flags`, `components` |
| `sw_component` | `sw_components` | HAL/kernel/firmware 단품 | `category`, `metadata.version`, `feature_flags`, `capabilities` |

`soc.dvfs_table`은 EVT revision과 독립적인 SoC-scoped sequence다.

- `dvfs_version`: 같은 `soc_ref` 안에서 증가하는 table version. EVT0 진행 중에도 v0, v1, v2처럼 계속 늘 수 있다.
- `evt_hint`: guide가 나온 시점이나 참고 EVT를 보존하는 메타데이터. 호환성 키나 version 축으로 쓰지 않는다.
- `domains`: voltage domain별 DVFS level table. voltage domain 구성이 과제마다 달라질 수 있으므로 `source_project_ref`와 `domain_schema_hash`로 출처/범위를 보존할 수 있다.

`ip_catalog.capabilities`는 현재 가장 중요한 확장 지점이다.

- `operating_modes`: `node_configs.*.selected_mode` 검증과 simulation mode 선택에 필요.
- `supported_features`: bitdepth, HDR, compression, crop/scale/rotate 같은 capability 검색에 필요.
- `sim`: power/timing/BW simulation에 필요. `ppc`, `unit_power_mw_mp`, `vdd`, `dvfs_group` 등이 없으면 readiness에서 error/warning이 난다.
- `properties`: sensor/display/module/DMA/internal edge 같은 category-specific detail 보존에 필요.

Sensor와 display는 별도 테이블이 아니라 `ip_catalog`에 넣는 것이 현재 구현의 기본이다.

```yaml
id: ip-sensor-rear-s5e9965
schema_version: "2.2"
kind: ip
category: sensor
hierarchy:
  type: simple
capabilities:
  operating_modes:
    - id: mode0
  supported_features:
    bitdepth: [10, 12]
  properties:
    modes:
      mode0:
        sensor_size: [4000, 3000]
        sensor_fps: 60
        sensor_format: BAYER
```

### 3.2 Definition Data

Definition data는 "어떤 project에서 어떤 scenario/variant를 검토하는가"를 담는다.

| YAML kind | DB table | 필수 성격 | Query/Viewer에서 중요한 필드 |
| --- | --- | --- | --- |
| `project` | `projects` | board/form-factor scope | `metadata.soc_ref`, `board_type`, `board_name`, `sensor_module_ref`, `display_module_ref`, `default_sw_profile_ref` |
| `scenario.usecase` | `scenarios` | base scenario superset topology | `project_ref`, `metadata.category`, `metadata.domain`, `pipeline.nodes/edges/buffers`, `size_profile`, `design_axes` |
| `scenario.usecase.variants[]` | `scenario_variants` | variant overlay | `design_conditions`, `severity`, `tags`, `size_overrides`, `routing_switch`, `topology_patch`, `node_configs`, `buffer_overrides` |

Base scenario는 한 variant의 실행 경로가 아니라, 물리적으로 가능한 superset topology가 되는 것이 좋다. Variant는 그 base에서 active path를 선택한다.

추천 분리 기준:

| 변화 종류 | 저장 위치 |
| --- | --- |
| resolution/fps/codec/HDR/sensor mode | `variant.design_conditions` |
| input/output size anchor | `variant.size_overrides` |
| IP selected mode, clock, port, format, task duration | `variant.node_configs` |
| buffer format, bitdepth, compression, alignment, LLC placement | `variant.buffer_overrides` |
| base에 존재하지만 variant에서 안 쓰는 node/edge | `variant.routing_switch.disabled_nodes/disabled_edges` |
| variant에서만 생기는 SW task detour | `variant.topology_patch.add_nodes/add_edges` |
| 모든 variant에 영향을 주는 base node/edge/buffer 변경 | `scenario.pipeline_patch` Write API |

Viewer fidelity를 높이려면 `pipeline.task_graph`, `pipeline.level1_graph`, `architecture_graph`도 넣는다. 없어도 기본 Level 0/1 projection은 가능하지만, 실제 task path와 module detail이 빈약해진다.

### 3.3 Evidence Data

Evidence data는 "실행했더니 어떤 KPI/feasibility가 나왔는가"를 담는다.

| YAML kind / API source | DB table | 필수 성격 | Query/Viewer에서 중요한 필드 |
| --- | --- | --- | --- |
| `evidence.simulation` | `evidence` | simulation 결과 | `scenario_ref`, `variant_ref`, `execution_context`, `run_info`, `aggregation`, `kpi`, `resolution_result`, `overall_feasibility` |
| `evidence.measurement` | `evidence` | 실측 결과 | `execution_context`, `provenance`, `aggregation`, `kpi` |
| Simulation API persisted run | `evidence` | API가 생성한 simulation evidence | `params_hash`, `dma_breakdown`, `timing_breakdown`, `dvfs_breakdown`, `timeline_events`, `artifacts` |

Architecture Query에서 `evidence.latest.*` 필드는 scenario/variant별 최신 evidence에서 온다.

- `evidence.latest.sw_version` = `sw_baseline_ref` 또는 generated `sw_version_hint`
- `evidence.latest.feasibility` = `overall_feasibility`
- `evidence.latest.kpi.*` = `kpi` JSON key

따라서 power/BW/latency query를 하려면 최소 한 개의 latest simulation 또는 measurement evidence가 있어야 한다.

KPI key는 lowercase snake_case여야 한다.

```yaml
kpi:
  total_power_mw: 2350
  avg_ddr_bw_gbps: 15
  frame_latency_ms: 17
```

### 3.4 Decision Data

Decision data는 "어떤 issue/rule/review/waiver가 이 variant에 영향을 주는가"를 담는다.

| YAML kind | DB table | 필수 성격 | 사용 기능 |
| --- | --- | --- | --- |
| `decision.issue` | `issues` | known issue catalog | matched issues, Architecture Query `issue.matched` |
| `decision.gate_rule` | `gate_rules` | review gate rule | runtime gate endpoint, review automation |
| `decision.waiver` | `waivers` | approved exception | gate/review exception tracking |
| `decision.review` | `reviews` | human review decision | review history and approval status |

초기 real-data 입력에서는 Decision data를 나중으로 미뤄도 된다. 하지만 "known issue가 걸리는 variant 찾기"나 "review gate 결과"까지 보고 싶으면 issue와 gate rule부터 넣어야 한다.

### 3.5 Write Audit Data

Write audit data는 사람이 직접 YAML로 넣는 데이터가 아니다.

| DB table | 생성 주체 | 의미 |
| --- | --- | --- |
| `write_batches` | Write API | staged/validated/diff_ready/applied 상태와 payload |
| `write_events` | Write API | stage, validate, diff, apply 이벤트 이력 |

Import Workbench와 Write API를 쓰면 자동으로 쌓인다. Direct ETL은 이 audit trail을 남기지 않는다.

## 4. Query Fields And Required Source Data

Architecture Query가 현재 지원하는 주요 field와 원천 데이터는 다음과 같다.

| Query field | Source |
| --- | --- |
| `project.soc_ref` | `projects.metadata.soc_ref` |
| `project.board_type` | `projects.metadata.board_type` |
| `scenario.category` | `scenarios.metadata.category` |
| `scenario.domain` | `scenarios.metadata.domain` |
| `variant.severity` | `scenario_variants.severity` |
| `variant.tags` | `scenario_variants.tags` |
| `variant.derived` | `scenario_variants.derived_from_variant` |
| `axis.<key>` | resolved `variant.design_conditions.<key>` |
| `topology.uses_ip` | effective pipeline nodes `ip_ref` |
| `topology.uses_ip_category` | effective node `ip_ref` -> `ip_catalog.category` |
| `topology.edge_type` | effective pipeline edges `type` |
| `topology.uses_buffer` | effective pipeline edges `buffer` |
| `topology.disabled_node` | `variant.routing_switch.disabled_nodes` |
| `buffer.compression` | scenario buffers plus `variant.buffer_overrides` |
| `buffer.format` | scenario buffers plus `variant.buffer_overrides` |
| `evidence.latest.sw_version` | latest evidence execution context |
| `evidence.latest.feasibility` | latest evidence `overall_feasibility` |
| `evidence.latest.kpi.<key>` | latest evidence `kpi.<key>` |
| `issue.matched` | `issues.affects` matched against variant context |

결론은 단순하다. 좋은 query를 만들려면 `design_conditions`, topology, buffer descriptor, latest evidence KPI를 비워두면 안 된다.

## 5. How To Add Data

### 5.1 Direct ETL

로컬 fixture, clean DB reload, controlled bulk load에 적합하다.

```powershell
cd E:\50_Codex_Soc_Scenario_DB\implementation
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:15432/scenario_db"
uv run alembic upgrade head
uv run python -m scenario_db.etl.loader demo\fixtures
```

Exynos2600 fixture family:

```powershell
uv run python -m scenario_db.etl.loader db_fixtures_Exynos2600_S26Plus --replace-scenario-project-collisions
```

Direct ETL supports the broadest canonical YAML set, including `sw_component`, `evidence.*`, and `decision.*`. It does not create Write API audit history.

### 5.2 Write API Import Bundle

real project data review path에 적합하다.

```text
canonical documents + import_report
  -> scenario.import_bundle
  -> stage
  -> validate
  -> diff
  -> apply
```

Supported bundle document kinds:

```text
soc
soc.dvfs_table
ip
sw_profile
project
scenario.usecase
```

PowerShell:

```powershell
$api="http://127.0.0.1:18000/api/v1"
$payload = Get-Content generated\scenariodb\import_bundle.json -Raw
$stage = Invoke-RestMethod -Method Post -Uri "$api/write/staging" -ContentType "application/json" -Body $payload
$validation = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$($stage.batch_id)/validate"
$diff = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$($stage.batch_id)/diff"

$validation.valid
$validation.import_report
$diff.impact

Invoke-RestMethod -Method Post -Uri "$api/write/staging/$($stage.batch_id)/apply"
```

### 5.3 Variant Overlay

기존 scenario에 새 variant 하나를 추가하거나 수정할 때 쓴다.

```text
kind: scenario.variant_overlay
payload.scenario_ref
payload.variant.id
payload.variant.design_conditions
payload.variant.node_configs
payload.variant.buffer_overrides
```

Base topology를 바꾸지 않는다. Read API와 Viewer는 read time에 resolved variant/effective topology를 만든다.

### 5.4 Pipeline Patch

base scenario의 `pipeline.nodes`, `pipeline.edges`, `pipeline.buffers`를 바꿀 때 쓴다. 모든 variant에 영향을 준다.

Use this only for common base changes:

- new physical IP node
- new base edge
- base buffer add/update/remove
- node role/ip_ref update

Apply 전에 diff `impact.blocking_variant_count`를 확인해야 한다.

### 5.5 Simulation Persist

simulation result를 evidence로 저장하려면 API request에 `persist=true`를 넣는다.

```json
{
  "scenario_id": "uc-camera-recording",
  "variant_id": "UHD60-HDR10-H265",
  "execution_context": {
    "silicon_rev": "EVT0",
    "sw_baseline_ref": "sw-vendor-v1.2.3",
    "thermal": "hot"
  },
  "persist": true,
  "force": false
}
```

저장된 evidence는 Evidence Dashboard, simulation overlay, Architecture Query `evidence.latest.*`에서 사용된다.

## 6. Existing Data Locations

| Path | Purpose |
| --- | --- |
| `demo/fixtures` | small golden canonical dataset |
| `db_fixtures_Exynos2600_S26Plus` | broader Exynos2600/S26Plus fixture family |
| `demo/generated/scenariodb` | generated canonical importer output smoke data |
| `demo/write_payloads` | Write API staging sample payloads |
| `demo/exploration_fixtures` | Exploration Workbench recipe/sweep/template examples |

## 7. Data Quality Checklist

Before applying real data, check this list.

- Every YAML has `id`, `schema_version`, and supported `kind`.
- ID prefix follows the canonical pattern, such as `soc-`, `dvfs-`, `ip-`, `sw-`, `proj-`, `uc-`, `sim-`, `meas-`, `iss-`, `rule-`.
- `soc.dvfs_table` uses unique `(soc_ref, dvfs_version)`; do not encode EVT as the DVFS version axis.
- `project.metadata.soc_ref` exists in `soc_platforms`.
- `project.metadata.sensor_module_ref` and `display_module_ref`, if present, exist in `ip_catalog`.
- `project.metadata.default_sw_profile_ref`, if present, exists in `sw_profiles`.
- `scenario.project_ref` exists in `projects`.
- Every `pipeline.nodes[].ip_ref` exists in `ip_catalog`.
- Every `pipeline.edges[].from/to` exists in `pipeline.nodes`.
- `OTF` edge does not declare `buffer`.
- `M2M` and `vOTF` edge declare `buffer`, and that buffer exists in `pipeline.buffers`.
- Every variant `node_configs` key references a base node or a valid injected SW node.
- Every variant `buffer_overrides` key references a base buffer.
- `node_configs.*.selected_mode`, if present, exists in the target IP `capabilities.operating_modes`.
- Compression stays in buffer descriptor or `buffer_overrides`; LLC allocation stays in `placement`.
- KPI keys are lowercase snake_case.

Import health API:

```powershell
$api="http://127.0.0.1:18000/api/v1"
Invoke-RestMethod "$api/explorer/import-health"
```

Useful smoke checks:

```powershell
Invoke-RestMethod "$api/explorer/summary"
Invoke-RestMethod "$api/explorer/scenario-catalog"
Invoke-RestMethod "$api/explorer/variant-matrix"
Invoke-RestMethod "$api/query/facets"
Invoke-RestMethod "$api/scenarios/uc-camera-recording/variants/UHD60-HDR10-H265/view?level=0&mode=resource"
Invoke-RestMethod "$api/simulation/readiness?scenario_id=uc-camera-recording&variant_id=UHD60-HDR10-H265"
```

## 8. Recommended Real Data Review Order

Use this order for the next DB data review.

1. Pick one SoC/project/board target.
2. Confirm `soc` and `ip` catalog completeness, especially sensor/display and active multimedia IPs.
3. Confirm `sw_profile` baseline and feature flags.
4. Review one `project` row for board metadata and default refs.
5. Review one `scenario.usecase` base topology as a superset, not as one concrete run.
6. Review variant overlays for real task cases.
7. Run Import Workbench or Write API `scenario.import_bundle` validation/diff.
8. Apply only after import health has no blocking errors.
9. Run Viewer Level 0 resource/topology, Level 1, and Level 2 checks.
10. Persist one simulation result and verify Architecture Query can filter by KPI.
11. Add issue/gate/review data only after the base scenario and variant facts are stable.

This keeps the first real DB milestone focused: make the core data searchable, viewable, and simulation-ready before expanding review automation.
