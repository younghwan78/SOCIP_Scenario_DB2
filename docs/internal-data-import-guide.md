# Internal Data Import Guide

이 문서는 사내 기존 YAML 데이터를 ScenarioDB PostgreSQL에 올리고 Viewer에서 확인하기 위한 실무 가이드다.

현재 상태를 먼저 명확히 구분한다.

- 가능: ScenarioDB canonical YAML 형식의 데이터를 PostgreSQL에 적재하고 FastAPI/Viewer에서 확인.
- 가능: sensor/display catalog를 `ip_catalog`의 `category: sensor`, `category: display`로 적재.
- 아직 직접 불가: `E:\10_Codes\23_MMIP_Scenario_simulation2`의 legacy simulation YAML을 그대로 `etl.loader`에 넣는 것.
- 필요 작업: legacy YAML을 canonical ScenarioDB YAML로 변환하는 importer/adapter.

즉, DB/ETL/API/Viewer 기반은 준비되어 있지만, 기존 simulation YAML을 실제 DB 입력으로 쓰려면 변환 단계가 필요하다.

## 1. Import Target

1차 목표:

```text
legacy YAML
  hw_config/projectA_hw.yaml
  hw_config/sensor_config.yaml
  scenario_config/*.yaml
        |
        v
legacy importer
        |
        v
canonical ScenarioDB YAML
        |
        v
PostgreSQL
        |
        v
FastAPI / Viewer
```

최종 확인 대상:

- `ip_catalog`: HW IP, sensor, display, memory, codec 등 catalog 적재 확인.
- `scenarios`: base scenario pipeline 적재 확인.
- `scenario_variants`: FHD30/FHD60/UHD30/UHD60 등 variant 적재 확인.
- Viewer Level 0/1/2: topology, task graph, buffer/memory 정보 확인.

## 2. Current Loader Contract

현재 canonical loader는 `kind` 값이 있는 YAML만 읽는다.

지원되는 주요 `kind`:

```text
soc
ip
sw_profile
sw_component
project
scenario.usecase
evidence.simulation
evidence.measurement
decision.gate_rule
decision.issue
decision.waiver
decision.review
```

따라서 아래 legacy YAML은 직접 적재되지 않는다.

```yaml
# projectA_hw.yaml
- name: "CSIS"
  type: "IP"
  modules: [...]
```

이 파일은 `kind: ip` 문서 여러 개로 변환되어야 한다.

## 3. Canonical Import Command

Windows 개발 환경:

```powershell
cd E:\50_Codex_Soc_Scenario_DB\implementation
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:5432/scenario_db"
uv run alembic upgrade head
uv run python -m scenario_db.etl.loader generated\scenariodb
```

Ubuntu 사내 서버:

```bash
cd /opt/scenariodb/implementation
set -a
source .env
set +a
uv run alembic upgrade head
uv run python -m scenario_db.etl.loader /opt/scenariodb/data/generated/scenariodb
```

주의:

- `etl.loader`는 현재 파일별 실패를 skip하고 계속 진행한다.
- 사내 데이터 최초 이관에서는 반드시 import log를 확인해야 한다.
- strict mode는 별도 구현 대상이다.

## 4. Legacy To Canonical Mapping

### 4.1 `projectA_hw.yaml` to `ip_catalog`

Legacy:

```yaml
- name: "CSIS"
  type: "IP"
  ip_group: "CSIS"
  hierarchy_group: "ISP"
  min_size: [64, 64]
  max_size: [8192, 8192]
  supports_crop: true
  supports_scale: false
  supported_modes:
    - "Normal"
  modules:
    - name: "CSIS_WDMA"
      type: "DMA"
      direction: "write"
      supported_compressions:
        - "COMP_BAYER_LOSSLESS"
  edges:
    - src: "sMCB"
      dst: "CSIS_WDMA"
```

Canonical:

```yaml
id: ip-csis-projectA
schema_version: "2.2"
kind: ip
category: camera
hierarchy:
  type: simple
capabilities:
  operating_modes:
    - id: Normal
  supported_features:
    crop: true
    scale: false
    compression: [COMP_BAYER_LOSSLESS]
  properties:
    legacy_name: CSIS
    ip_group: CSIS
    hierarchy_group: ISP
    min_size: [64, 64]
    max_size: [8192, 8192]
    modules:
      - name: CSIS_WDMA
        type: DMA
        direction: write
        supported_compressions: [COMP_BAYER_LOSSLESS]
    internal_edges:
      - {from: sMCB, to: CSIS_WDMA}
```

수정이 필요한 경우:

| 증상 | 원인 | 수정 |
| --- | --- | --- |
| `kind`가 없어서 loader가 무시 | legacy HW list 형식 | IP별 `kind: ip` 문서로 변환 |
| `id` validation 실패 | `CSIS` 같은 raw 이름 사용 | `ip-csis-projectA`처럼 prefix 포함 ID 사용 |
| `capabilities` validation 실패 | 알 수 없는 필드가 직접 들어감 | category-specific 필드는 `capabilities.properties` 아래로 이동 |
| DMA compression이 Viewer에 안 보임 | DMA 정보를 버림 | `properties.modules` 또는 `properties.dma_ports`에 보존 |

### 4.2 `sensor_config.yaml` to sensor catalog

Legacy:

```yaml
sensors:
  HP2:
    mode0:
      sensor_size: [4000, 2252]
      sensor_fps: 60.0
      sensor_mipi_speed: 3.712
      sensor_format: BAYER
      sensor_bitwidth: 12
```

Canonical:

```yaml
id: ip-sensor-hp2-projectA
schema_version: "2.2"
kind: ip
category: sensor
hierarchy:
  type: simple
capabilities:
  operating_modes:
    - id: mode0
  supported_features:
    bitdepth: [12]
  properties:
    legacy_name: HP2
    modes:
      mode0:
        sensor_size: [4000, 2252]
        sensor_fps: 60.0
        sensor_mipi_speed: 3.712
        sensor_format: BAYER
        sensor_bitwidth: 12
```

수정이 필요한 경우:

| 증상 | 원인 | 수정 |
| --- | --- | --- |
| scenario에서 sensor를 찾지 못함 | `sensor.hw`와 catalog `legacy_name` 불일치 | `legacy_name` 또는 importer 매핑 테이블 수정 |
| mode를 찾지 못함 | `sensor.mode`가 catalog `modes`에 없음 | sensor catalog에 mode 추가 |
| MIPI/vValid 계산 불가 | `sensor_pclk` 또는 `sensor_line_length_pck` 누락 | 가능한 경우 sensor mode에 필드 추가, 없으면 warning 처리 |

### 4.3 Display catalog

현재 필요한 최소 display 정보:

- display size, pixel 단위
- ppi
- refresh rate, fps 또는 Hz

Canonical:

```yaml
id: ip-display-fhd-panel-projectA
schema_version: "2.2"
kind: ip
category: display
hierarchy:
  type: simple
capabilities:
  operating_modes:
    - id: 60hz
    - id: 120hz
  supported_features:
    bitdepth: [8, 10]
    hdr_formats: [SDR, HDR10]
  properties:
    legacy_name: FHD_PANEL
    display_size: [2400, 1080]
    ppi: 420
    refresh_rates: [60, 120]
```

수정이 필요한 경우:

| 증상 | 원인 | 수정 |
| --- | --- | --- |
| DPU와 panel이 구분되지 않음 | display controller와 external panel이 같은 category | 우선 둘 다 `display`, 필요 시 `properties.role: controller/panel` 추가 |
| refresh rate가 variant와 맞지 않음 | variant `fps`와 display `refresh_rates` 불일치 | display catalog에 지원 refresh rate 추가 또는 variant 조건 수정 |
| Viewer에 display target이 안 보임 | scenario pipeline에 display node 없음 | base scenario에 display panel node 추가 |

### 4.4 Legacy scenario to `scenario.usecase`

Legacy scenario는 한 파일이 하나의 concrete run에 가깝다.

ScenarioDB에서는 다음처럼 분리한다.

```text
base scenario: camera-recording
variant: FHD30-Recording
variant: FHD60-Recording
variant: UHD30-Recording
variant: UHD60-Recording
```

Base scenario:

- 물리적으로 가능한 superset topology.
- sensor, CSIS, ISP, MFC, DPU, memory/display path.
- 가능한 HW edge 후보.
- 공통 buffer 후보.

Variant:

- resolution/fps/codec/sensor mode.
- IP mode.
- input/output size.
- DMA 사용 여부.
- format/bitwidth/compression.
- SW task 삽입.

## 5. Variant Pattern Guide

기본 원칙:

```text
Default: Superset & Switch
Exception: Delta Patch for SW/task insertion
```

### 5.1 Use Superset & Switch

사용 상황:

- HW에 존재하는 edge/path 중 variant에서 일부만 사용.
- preview path on/off.
- MFC/DPU output 선택.
- bypass 가능한 IP block.
- OTF/M2M 후보가 모두 물리적으로 존재.

저장 위치:

```yaml
routing_switch:
  disabled_edges:
    - {from: mcsc, to: dpu}
  disabled_nodes:
    - dpu
```

변환 실패 시 수정:

| 증상 | 원인 | 수정 |
| --- | --- | --- |
| `unknown_disabled_edge` | base pipeline에 edge가 없음 | base scenario에 superset edge 추가 또는 disabled edge 제거 |
| `unknown_disabled_node` | base pipeline에 node가 없음 | base scenario node ID 확인 |
| Viewer에서 path가 계속 보임 | disable target이 task ID인지 IP node ID인지 혼동 | importer의 node ID convention 통일 |

### 5.2 Use Delta Patch

사용 상황:

- SW task가 중간에 삽입됨.
- CPU/GPU/NPU task가 memory buffer를 소비/생산함.
- debug/filter/postprocessing task가 variant에서만 존재.

저장 위치:

```yaml
topology_patch:
  remove_edges:
    - {from: mcsc, to: mfc}
  add_nodes:
    - {id: sw_filter, node_type: SW, layer: kernel}
  add_edges:
    - {from: mcsc, to: sw_filter, type: M2M, buffer: RECORD_BUF}
    - {from: sw_filter, to: mfc, type: control}
```

변환 실패 시 수정:

| 증상 | 원인 | 수정 |
| --- | --- | --- |
| `hw_node_injection_forbidden` | variant patch로 HW node 추가 시도 | base scenario에 `scenario.pipeline_patch`로 추가 |
| `sw_patch_edge_type_invalid` | SW patch에 OTF/vOTF 사용 | SW task 연결은 `M2M` 또는 `control`로 표현 |
| `added_edge_missing_endpoint` | add_edges endpoint가 없음 | add_nodes 또는 base node ID 확인 |

### 5.3 IP mode is config, not topology

IP mode 변경은 graph patch가 아니다.

```yaml
node_configs:
  mfc:
    selected_mode: LowPower
    target_clock_mhz: 333
```

변환 실패 시 수정:

| 증상 | 원인 | 수정 |
| --- | --- | --- |
| `unsupported_selected_mode` | HW catalog에 mode 없음 | `capabilities.operating_modes`에 mode 추가 |
| target clock validation 실패 | selected mode의 max clock 초과 | mode 선택 또는 clock 값 수정 |
| mode 이름 불일치 | `Normal` vs `normal` 혼용 | importer에서 mode naming normalize 또는 catalog 이름 통일 |

## 6. Minimum Generated Canonical Files

사내 legacy import pilot에서 최소로 생성되어야 하는 파일:

```text
generated/scenariodb/
  00_hw/
    soc-projectA.yaml
    ip-*.yaml
    ip-sensor-*.yaml
    ip-display-*.yaml
  02_definition/
    proj-projectA.yaml
    uc-camera-recording.yaml
```

Optional:

```text
  01_sw/
    sw_profile / sw_component
  03_evidence/
  04_decision/
```

## 7. Pre-Import Checklist

Before loading generated YAML:

- Every YAML has `kind`.
- Every YAML has `schema_version`.
- Every document ID uses allowed prefix such as `ip-`, `soc-`, `proj-`, `uc-`.
- Every `scenario.pipeline.nodes[*].ip_ref` exists in `ip_catalog`.
- Every `scenario.pipeline.edges[*].from/to` exists in pipeline nodes.
- Every `M2M` edge has `buffer`.
- Every M2M edge buffer exists in `pipeline.buffers`.
- Every variant `node_configs` key exists in base pipeline nodes or injected SW nodes.
- Every variant `buffer_overrides` key exists in base buffers.
- Sensor selected by scenario exists in sensor catalog.
- Display selected by scenario exists in display catalog.

## 8. Import Failure Guide

### 8.1 YAML parse failed

Typical log:

```text
YAML parse failed projectA_hw.yaml: ...
```

Likely cause:

- Invalid indentation.
- Tab character.
- Unquoted colon in string.
- Encoding issue.

Fix:

- Validate YAML with editor or `python -c`.
- Keep generated YAML UTF-8.

### 8.2 No mapper for kind

Typical log:

```text
no mapper for kind=...
```

Likely cause:

- Unsupported `kind`.
- Typo such as `scenario_usecase` instead of `scenario.usecase`.

Fix:

- Use supported kind names only.
- For sensor/display, use `kind: ip` plus `category: sensor/display`.

### 8.3 Pydantic validation error

Likely cause:

- Extra field placed at wrong level.
- ID pattern invalid.
- Required field missing.

Fix:

- Move category-specific fields under `capabilities.properties`.
- Check ID prefix.
- Check `schema_version`, `kind`, `hierarchy`, `capabilities`.

### 8.4 Scenario edge reference error

Typical cause:

- Edge endpoint does not exist in `pipeline.nodes`.
- Legacy task ID and generated node ID differ.

Fix:

- Decide node ID convention.
- Use one of:
  - IP-level node IDs: `csis`, `isp`, `mfc`
  - task-level node IDs: `t_csis`, `t_mfc`
- Do not mix both in the same pipeline edge list.

### 8.5 M2M buffer error

Typical cause:

- Legacy M2M edge has `src_port/dst_port`, but generated canonical edge has no `buffer`.

Fix:

- Generate deterministic buffer ID from ports:

```text
{src_port}_{dst_port}
CSIS_WDMA_COMP_RD0_RDMA
```

- Add descriptor under `pipeline.buffers`.
- Add edge `buffer` reference.

### 8.6 Viewer shows too little detail

Likely cause:

- Only base `pipeline.nodes/edges` generated.
- `pipeline.task_graph` or `level1_graph` not generated.
- Buffer descriptors missing format/size/compression.

Fix:

- Generate `pipeline.task_graph` from legacy `tasks` and `ip_blocks.edges`.
- Preserve `src_port`, `dst_port`, `format`, `bitwidth`, `comp`.
- Add `properties.modules` and `internal_edges` to IP catalog.

## 9. Post-Import Smoke Checks

API:

```powershell
$api="http://127.0.0.1:18000/api/v1"
Invoke-RestMethod "$api/ip-catalogs?category=sensor"
Invoke-RestMethod "$api/ip-catalogs?category=display"
Invoke-RestMethod "$api/scenarios"
Invoke-RestMethod "$api/scenarios/uc-camera-recording/variants"
Invoke-RestMethod "$api/scenarios/uc-camera-recording/variants/FHD30-Recording/view?level=0&mode=architecture"
Invoke-RestMethod "$api/scenarios/uc-camera-recording/variants/FHD30-Recording/view?level=0&mode=topology"
```

Viewer:

- Select imported scenario.
- Select imported variant.
- Check Level 0 architecture.
- Check Level 0 task topology.
- Check Level 1 IP detail.
- Check Level 2 camera/video/display drill-down if available.

DB:

```sql
select id, category from ip_catalog order by category, id;
select id, project_ref from scenarios;
select scenario_id, id from scenario_variants order by scenario_id, id;
```

## 10. Recommended Pilot Procedure

Do not start with all legacy scenarios.

Recommended order:

1. Convert `projectA_hw.yaml`.
2. Convert `sensor_config.yaml`.
3. Add one display sidecar or display catalog.
4. Convert only `projectA_FHD30_recording_scenario.yaml`.
5. Load generated YAML into a fresh DB.
6. Verify API.
7. Verify Viewer.
8. Convert FHD60/UHD30/UHD60.
9. Group variants under one base scenario.
10. Only then scale to more scenarios.

## 11. What To Implement Next

Required before real legacy import is convenient:

1. `scenario_db.legacy_import` package.
2. CLI:

```bash
uv run python -m scenario_db.legacy_import.cli \
  --hw legacy/hw_config/projectA_hw.yaml \
  --sensor legacy/hw_config/sensor_config.yaml \
  --display legacy/hw_config/display_config.yaml \
  --scenario-dir legacy/scenario_config \
  --project proj-projectA \
  --out generated/scenariodb \
  --strict
```

3. Strict report:

```json
{
  "errors": [],
  "warnings": [],
  "generated": {
    "ip_catalog": 42,
    "sensor_catalog": 2,
    "display_catalog": 1,
    "scenarios": 1,
    "variants": 4
  }
}
```

4. Generated YAML review before DB load.

## 12. Current Readiness Summary

Ready now:

- PostgreSQL schema.
- Canonical YAML ETL.
- sensor/display as catalog categories.
- Read API.
- Viewer.
- Write API for variant overlay and base pipeline patch.

Not ready yet:

- Direct legacy simulation YAML import.
- Automatic grouping of multiple scenario YAML files into one base scenario with variants.
- Strict importer report.
- Automatic conversion of compact scenario syntax.
- Full validation of legacy port-level DMA/SYSMMU details.

Therefore, the next implementation milestone should be:

```text
legacy_import scaffold
  -> HW/sensor/display conversion
  -> one FHD30 scenario conversion
  -> generated canonical YAML
  -> DB load
  -> Viewer smoke
```

## 13. Current Legacy Importer Command

The current importer scaffold converts legacy HW, sensor, and optional display
sidecar YAML into canonical `kind: ip` catalog YAML files. This is the Step 3C
scope: catalog import only. Scenario YAML, variants, and pipeline generation are
still handled in the next importer step.

Example:

```powershell
cd E:\50_Codex_Soc_Scenario_DB\implementation
uv run python -m scenario_db.legacy_import.cli `
  --hw E:\10_Codes\23_MMIP_Scenario_simulation2\hw_config\projectA_hw.yaml `
  --sensor E:\10_Codes\23_MMIP_Scenario_simulation2\hw_config\sensor_config.yaml `
  --display generated\display_config.yaml `
  --out generated\scenariodb `
  --project proj-projectA `
  --strict
```

If no display YAML exists in the legacy repo yet, create a small sidecar file
before running the importer:

```yaml
displays:
  FHD_PANEL:
    display_size: [2400, 1080]
    ppi: 420
    refresh_rates: [60, 120]
    bitdepth: [8, 10]
    hdr_formats: [SDR, HDR10]
```

Output:

```text
generated/scenariodb/
  00_hw/
    ip-*.yaml
  import_report.json
```

Current importer scope:

- Converts `projectA_hw.yaml` list entries into `ip_catalog` YAML.
- Converts `sensor_config.yaml` entries into `category: sensor` catalog YAML.
- Converts optional display sidecar entries into `category: display` catalog YAML.
- Preserves modules, DMA ports, internal edges, min/max size, crop/scale/rotate flags, supported modes, and compression data.
- Preserves sensor modes and calculates `v_valid_ms` when `sensor_size`, `sensor_pclk`, and `sensor_line_length_pck` are available.
- Preserves display size, PPI, refresh rates, bitdepth, and HDR formats.
- Emits an import report.
- Does not yet convert scenario YAML or variants.

After generation, load the generated YAML with the normal canonical ETL:

```powershell
uv run python -m scenario_db.etl.loader generated\scenariodb
```
