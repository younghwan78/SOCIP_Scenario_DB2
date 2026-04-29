# Legacy YAML Import Plan

This document defines the plan for importing existing
`E:\10_Codes\23_MMIP_Scenario_simulation2` YAML assets into ScenarioDB.

The first target is practical:

- Load existing project HW configuration into PostgreSQL.
- Load sensor and display catalog data.
- Convert existing per-scenario YAML into canonical ScenarioDB scenarios and variants.
- Verify the result through FastAPI Read API and the Viewer.

## 1. Current Legacy YAML Shape

The existing simulation project has three primary YAML inputs.

### 1.1 `hw_config/projectA_hw.yaml`

Purpose:

- Defines project multimedia HW blocks.
- Each IP has submodules, DMA ports, and internal edges.
- Each IP declares capability-like fields such as min/max size, crop/scale support, supported modes.
- DMA modules may declare direction, max bandwidth, outstanding count, supported compression, and compression ratio.
- CPU exists approximately; GPU/NPU are not yet modeled.

Important fields:

```yaml
- name: "CSIS"
  type: "IP"
  ip_group: "CSIS"
  hierarchy_group: "ISP"
  min_size: [64, 64]
  max_size: [8192, 8192]
  supports_crop: true
  supports_scale: false
  supported_modes: ["Normal"]
  modules:
    - name: "CSIS_WDMA"
      type: "DMA"
      direction: "write"
      max_bandwidth: 25600000000
      supported_compressions: ["COMP_BAYER_LOSSLESS"]
  edges:
    - src: "sMCB"
      dst: "CSIS_WDMA"
```

### 1.2 `hw_config/sensor_config.yaml`

Purpose:

- Defines board-connectable external sensor modules.
- Required for sensor size, FPS, MIPI speed, bitwidth, and vValid-style timing calculation.

Important fields:

```yaml
sensors:
  HP2:
    mode0:
      sensor_name: "A-08 SENSOR_HP2_4000x2252_60FPS_12BIT"
      sensor_size: [4000, 2252]
      sensor_fps: 60.0
      sensor_mipi_speed: 3.712
      sensor_format: BAYER
      sensor_bitwidth: 12
```

### 1.3 `scenario_config/projectA_FHD30_recording_scenario.yaml`

Purpose:

- Defines one concrete simulation scenario today.
- References `hw_config` and `sensor_config`.
- Contains selected sensor mode.
- Contains IP settings, input/output ports, sizes, formats, compression, and task edges.
- May contain SW task insertion through CPU.
- `hw_info` and `hw_dvfs` are simulation inputs and can be ignored in the first DB import step.

Important fields:

```yaml
name: "FHD30_Recording"
config_paths:
  hw_config: "../hw_config/projectA_hw.yaml"
  sensor_config: "../hw_config/sensor_config.yaml"
sensor:
  hw: "HP2"
  mode: "mode1"
ip_blocks:
  - ip_settings:
      hw: "CSIS"
      mode: "Normal"
      inputs:
        - port: "NFI_DEC"
          size: [0, 0, 4000, 2252]
      outputs:
        - port: "CSIS_WDMA"
          size: [0, 0, 4000, 2252]
          format: "BAYER_PACKED"
          bitwidth: 12
          comp: "enable"
    tasks:
      - id: "t_csis"
        hw: "CSIS"
    edges:
      - src: "t_csislink"
        src_port: "LINK"
        dst: "t_csis"
        dst_port: "NFI_DEC"
        type: "OTF"
```

## 2. Key Conclusion

The legacy YAML should not be loaded directly by the current canonical ETL
loader.

Reasons:

- The current ETL loader expects documents with `kind`, `schema_version`, and canonical ScenarioDB shape.
- Legacy HW YAML is a list, not `kind: ip`.
- Legacy scenario YAML is a simulation input, not a canonical `scenario.usecase`.
- Sensor and display catalog data need category-specific capability fields that the current Pydantic capability model does not yet allow.

Therefore the correct implementation is a dedicated legacy importer:

```text
legacy YAML
  -> legacy parser/normalizer
  -> canonical ScenarioDB documents or direct DB rows
  -> PostgreSQL
  -> FastAPI Read API
  -> Viewer
```

## 3. Target Canonical Mapping

### 3.1 HW IP Catalog

Legacy `projectA_hw.yaml` entries should map to `ip_catalog`.

| Legacy Field | ScenarioDB Target |
| --- | --- |
| `name` | `ip_catalog.id`, normalized as `ip-{name}-projectA` or stable alias |
| `ip_group` | `category` or `capabilities.properties.ip_group` |
| `hierarchy_group` | `capabilities.properties.hierarchy_group` |
| `min_size` | `capabilities.properties.min_size` |
| `max_size` | `capabilities.properties.max_size` |
| `supports_crop` | `capabilities.supported_features.crop` or `properties.supports_crop` |
| `supports_scale` | `capabilities.supported_features.scale` or `properties.supports_scale` |
| `supported_modes` | `capabilities.operating_modes[*].id` |
| `modules` | `hierarchy.submodules` or `capabilities.properties.modules` |
| `edges` | `capabilities.properties.internal_edges` |
| DMA module fields | `capabilities.properties.dma_ports` |

Recommended first implementation:

- Keep each legacy IP as one `kind: ip` catalog row.
- Store detailed submodule/DMA/internal-edge data under `capabilities.properties`.
- Do not create thousands of `submodule` YAML documents in Step 1.
- Later, promote submodules/DMA/SYSMMU into first-class tables only when query requirements prove it is needed.

Example canonical shape:

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
    bitdepth: [8, 10, 12]
    compression: [COMP_BAYER_LOSSLESS, COMP_BAYER_LOSSY]
  properties:
    legacy_name: CSIS
    ip_group: CSIS
    hierarchy_group: ISP
    min_size: [64, 64]
    max_size: [8192, 8192]
    supports_crop: true
    supports_scale: false
    modules:
      - name: CSIS_WDMA
        type: DMA
        direction: write
        max_bandwidth: 25600000000
        supported_compressions: [COMP_BAYER_LOSSLESS, COMP_BAYER_LOSSY]
    internal_edges:
      - {from: sMCB, to: CSIS_WDMA}
```

## 4. Sensor Category Catalog

Sensor should be added as a capability catalog category.

For Step 1, store sensors in `ip_catalog` with `category: sensor`.

Reason:

- It avoids a new table before the first import.
- Existing pipeline nodes already reference `ip_ref`.
- Viewer can render sensor nodes through the same catalog path.
- Sensor-specific fields can live in `capabilities.properties`.

Recommended canonical shape:

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
    - id: mode1
  supported_features:
    bitdepth: [12]
  properties:
    legacy_name: HP2
    modes:
      mode0:
        sensor_name: "A-08 SENSOR_HP2_4000x2252_60FPS_12BIT"
        sensor_size: [4000, 2252]
        sensor_fps: 60.0
        sensor_pclk: 1760000000
        sensor_line_length_pck: 6440
        sensor_format: BAYER
        sensor_bitwidth: 12
        sensor_ln_mode: 1
        sensor_mipi_speed: 3.712
        sensor_sbwc: enable
        sensor_phy_type: CPHY
```

Fields needed for architecture exploration:

- `sensor_size`
- `sensor_fps`
- `sensor_format`
- `sensor_bitwidth`
- `sensor_mipi_speed`
- `sensor_phy_type`
- `sensor_ln_mode`
- `sensor_pclk`
- `sensor_line_length_pck`
- calculated `v_valid_ms`, when available

Future promotion path:

- If sensor query becomes important, add `sensor_modules` and `sensor_modes` tables.
- Keep `ip_catalog.category=sensor` as a compatibility view or reference row.

## 5. Display Category Catalog

Display should also be added as a capability catalog category.

For Step 1, store display panels or output targets in `ip_catalog` with
`category: display`.

The current minimal fields are:

- Display size in pixels.
- PPI.
- Refresh rate in FPS/Hz.

Recommended canonical shape:

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

The existing `ip-dpu-v9` remains the display controller IP. The new display
catalog entry represents the external panel/output target.

Recommended modeling:

```text
DPU controller: category=display_controller or display
Display panel:  category=display
```

For the first implementation, avoid adding a new category enum. Use free-form
`category` values:

- `camera`
- `codec`
- `display`
- `memory`
- `sensor`

If ambiguity becomes a problem, split `display` into:

- `display_controller`
- `display_panel`

## 6. Required Model Change

The current capability Pydantic model is too narrow for legacy import.

Current issue:

- `IpCapabilities` allows only `operating_modes` and `supported_features`.
- All models inherit `extra="forbid"`.
- Sensor/display/HW internal module details cannot be stored without model changes.

Recommended change:

```python
class IpCapabilities(BaseScenarioModel):
    operating_modes: list[OperatingMode] = Field(default_factory=list)
    supported_features: SupportedFeatures | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
```

Also extend `SupportedFeatures`:

```python
class SupportedFeatures(BaseScenarioModel):
    bitdepth: list[int] = Field(default_factory=list)
    hdr_formats: list[str] = Field(default_factory=list)
    compression: list[str] = Field(default_factory=list)
    crop: bool | None = None
    scale: bool | None = None
    rotate: bool | None = None
```

This preserves fixed DB schema while allowing category-specific catalog details
inside JSONB.

## 7. Scenario And Variant Strategy

The legacy project currently tends to define one YAML file per scenario:

```text
FHD30_Recording.yaml
FHD60_Recording.yaml
UHD30_Recording.yaml
UHD60_Recording.yaml
```

For ScenarioDB, this should become:

```text
scenario.usecase: camera-recording
  base pipeline:
    physically possible shared topology
  variants:
    FHD30
    FHD60
    UHD30
    UHD60
```

### 7.1 Base Scenario

Base scenario should contain the superset topology:

- Sensor node.
- CSIS/ISP/codec/display/memory nodes.
- Base physical IP edges.
- Common buffers when stable.
- Optional `task_graph` and `level1_graph` projection hints for professional viewer rendering.

The base scenario should not encode a single resolution or FPS.

### 7.1.1 Topology Pattern Decision

Use a hybrid pattern:

```text
Default:   Superset & Switch
Exception: Delta Patch for SW-task injection and rare non-physical task detours
```

This is the right fit for Android SoC multimedia pipelines because HW routes
are constrained by silicon reality. A variant should not invent a new HW OTF or
DMA route that is not physically possible in the base scenario. Instead, the
base scenario should contain the physically possible superset topology, and each
variant should select the active route.

Recommended rule:

| Variant Change Type | Pattern | Storage Field |
| --- | --- | --- |
| Resolution/FPS/codec/HDR/sensor mode | Delta config | `design_conditions`, `size_overrides` |
| IP operating mode | Delta config | `node_configs.*.selected_mode` |
| IP port size/format/bitwidth/compression | Delta config | `node_configs`, `buffer_overrides` |
| DMA path exists in silicon but is inactive for a variant | Superset & Switch | `routing_switch.disabled_edges` |
| IP block exists but is bypassed for a variant | Superset & Switch | `routing_switch.disabled_nodes` |
| MFC path vs DPU path selection | Superset & Switch | `routing_switch` |
| SW task inserted between HW blocks | Delta Patch | `topology_patch.add_nodes/add_edges` |
| CPU/GPU/NPU task insertion in future | Delta Patch if task-level only | `topology_patch` |
| New HW edge absent from base scenario | Base update, not variant | `scenario.pipeline_patch` |
| New physical IP/DMA/buffer route common to scenario family | Base update | `scenario.pipeline_patch` |

This preserves two important guarantees:

- Variant overlays cannot create physically impossible HW topology.
- SW/task-level flexibility remains available where software can realistically
  insert processing.

### 7.1.2 Superset & Switch Semantics

The base scenario stores all physically possible route candidates:

```text
MCSC -> MFC
MCSC -> DPU
MCSC -> Memory
MLSC -> MTNR0
MLSC -> MTNR1
```

Each variant disables unused routes:

```yaml
routing_switch:
  disabled_edges:
    - {from: mcsc, to: dpu}
  disabled_nodes:
    - dpu
```

Use this for:

- Preview on/off.
- Recording-only vs recording-with-display.
- Bypass-able IP blocks.
- OTF vs M2M alternative paths when both are physically represented.
- Multiple DMA output choices where the DMA ports exist in the HW catalog.

Do not use `routing_switch` to encode port sizes, formats, compression, or IP
mode. Those are node/buffer configuration deltas.

### 7.1.3 Delta Patch Semantics

`topology_patch` is allowed for flexible task-level changes, especially SW task
insertion:

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

Use this for:

- CPU preprocessing/postprocessing task.
- SW codec/filter/debug task.
- Future GPU/NPU task insertion, if the task consumes/produces memory buffers
  rather than requiring a new physical HW edge.

Do not use variant `topology_patch` for new HW routes. If a variant needs a HW
edge not present in base topology, the correct workflow is:

```text
scenario.pipeline_patch
  -> validate physical edge and buffer references
  -> diff impact on all existing variants
  -> apply to base scenario
  -> variants select it through routing_switch/node_configs
```

### 7.1.4 IP Mode And DMA Are Not Topology Patches

IP operating mode differences are variant configuration, not graph patches.

Example:

```yaml
node_configs:
  mfc:
    selected_mode: LowPower
    target_clock_mhz: 333
```

The HW catalog defines supported modes:

```yaml
capabilities:
  operating_modes:
    - id: Normal
      max_clock_mhz: 800
    - id: LowPower
      max_clock_mhz: 400
```

Validation should reject:

- A variant selecting a mode not supported by the IP.
- A target clock exceeding the selected mode limit.
- A compression mode not supported by the selected DMA port.

DMA usage should be represented in two layers:

- HW catalog: what DMA ports exist and what they support.
- Variant config: which DMA ports are used with what format/bitwidth/compression.

Recommended variant representation:

```yaml
node_configs:
  csis:
    outputs:
      - port: CSIS_WDMA
        size: [0, 0, 4000, 2252]
        format: BAYER_PACKED
        bitwidth: 12
        comp: enable
        comp_ratio: 0.5
buffer_overrides:
  CSIS_WDMA_COMP_RD0_RDMA:
    format: BAYER_PACKED
    bitdepth: 12
    compression: COMP_BAYER_LOSSY
```

This keeps graph topology stable while still capturing the detailed behavior
needed for BW/performance review.

### 7.2 Variant Overlay

Each legacy scenario YAML should map to one variant overlay.

Variant fields:

| Legacy Scenario Data | Variant Target |
| --- | --- |
| `name: FHD30_Recording` | `variant.id: FHD30-Recording` |
| sensor `hw/mode` | `design_conditions.sensor`, `design_conditions.sensor_mode` |
| FHD/UHD/8K | `design_conditions.resolution` |
| 30/60/120 | `design_conditions.fps` |
| IP mode | `node_configs.{node}.selected_mode` |
| IP input/output sizes | `node_configs.{node}.inputs/outputs` |
| port format/bitwidth/compression | `node_configs` and `buffer_overrides` |
| M2M edge data | `buffer_overrides` |
| SW task insertion | `topology_patch.add_nodes/add_edges` |
| disabled path | `routing_switch.disabled_nodes/disabled_edges` |

Recommended variant shape:

```yaml
- id: FHD30-Recording
  severity: medium
  design_conditions:
    usecase: recording
    resolution: FHD
    fps: 30
    sensor: HP2
    sensor_mode: mode1
    codec: H.265
  size_overrides:
    sensor_full: "4000x2252"
    record_out: "1920x1080"
    preview_out: "1920x1080"
  node_configs:
    csis:
      selected_mode: Normal
      inputs:
        - port: NFI_DEC
          size: [0, 0, 4000, 2252]
      outputs:
        - port: CSIS_WDMA
          size: [0, 0, 4000, 2252]
          format: BAYER_PACKED
          bitwidth: 12
          comp: enable
    mfc:
      selected_mode: Normal
  buffer_overrides:
    CSIS_WDMA_COMP_RD0_RDMA:
      format: BAYER_PACKED
      bitdepth: 12
      compression: COMP_BAYER_LOSSY
```

## 8. Variant Generation Strategy

Manual authoring of every FHD/UHD/FPS combination will not scale.

Recommended approach:

### 8.1 Keep One Base Scenario Per Usecase

Examples:

- `camera-recording`
- `camera-preview`
- `video-playback`
- `camera-recording-with-preview`

### 8.2 Define Variant Axes

For recording:

```yaml
variant_axes:
  resolution: [FHD, UHD, 8K]
  fps: [30, 60, 120]
  codec: [H.264, H.265, AV1]
  hdr: [SDR, HDR10, HDR10plus]
  sensor_mode: [mode0, mode1]
```

Do not create DB columns from axes. Store axes in JSONB and promote only needed
query fields later.

### 8.3 Define Size Profiles

```yaml
size_profiles:
  FHD:
    record_out: "1920x1080"
    preview_out: "1920x1080"
  UHD:
    record_out: "3840x2160"
    preview_out: "1920x1080"
```

### 8.4 Generate Variants By Template

The importer should support:

```bash
uv run python -m scenario_db.legacy_import.cli \
  --hw E:/10_Codes/23_MMIP_Scenario_simulation2/hw_config/projectA_hw.yaml \
  --sensor E:/10_Codes/23_MMIP_Scenario_simulation2/hw_config/sensor_config.yaml \
  --scenario-dir E:/10_Codes/23_MMIP_Scenario_simulation2/scenario_config \
  --project proj-A \
  --out generated/scenariodb
```

The first version should generate canonical YAML output, not write directly to
DB. This makes review and diff easier.

Then load generated YAML with the existing canonical ETL:

```bash
uv run python -m scenario_db.etl.loader generated/scenariodb
```

## 9. Importer Architecture

Recommended package:

```text
src/scenario_db/legacy_import/
  __init__.py
  cli.py
  read_legacy.py
  normalize_hw.py
  normalize_sensor.py
  normalize_display.py
  normalize_scenario.py
  variant_builder.py
  emit_canonical_yaml.py
  report.py
```

### 9.1 `read_legacy.py`

Responsibilities:

- Load raw legacy YAML.
- Expand `compact: true` scenarios.
- Resolve scenario-relative `config_paths`.
- Preserve source file path and SHA for traceability.

Reuse if practical:

- Existing `src/model/compact_scenario.py` logic from the legacy repo.

### 9.2 `normalize_hw.py`

Responsibilities:

- Convert `projectA_hw.yaml` list entries into canonical `kind: ip` documents.
- Normalize stable IP IDs.
- Extract DMA ports.
- Extract internal edges.
- Extract crop/scale/rotate capability flags.
- Keep legacy details under `capabilities.properties`.

### 9.3 `normalize_sensor.py`

Responsibilities:

- Convert `sensor_config.yaml` into `category: sensor` catalog entries.
- Preserve mode-level fields.
- Calculate `v_valid_ms` when possible.

### 9.4 `normalize_display.py`

Responsibilities:

- Convert display config into `category: display` catalog entries.
- If no display YAML exists yet, support a small sidecar file:

```yaml
displays:
  FHD_PANEL:
    display_size: [2400, 1080]
    ppi: 420
    refresh_rates: [60, 120]
```

### 9.5 `normalize_scenario.py`

Responsibilities:

- Convert each legacy scenario YAML into a candidate variant.
- Extract task graph from `tasks`, `ip_blocks.tasks`, and `ip_blocks.edges`.
- Convert IP blocks into `node_configs`.
- Convert M2M paths into buffer descriptors.
- Detect SW task insertion.

### 9.6 `variant_builder.py`

Responsibilities:

- Group related legacy scenario files into one base scenario.
- Generate variant IDs such as `FHD30-Recording`, `UHD60-Recording`.
- Identify common topology and variant-specific deltas.
- Optionally generate synthetic variants from axes.

### 9.7 `emit_canonical_yaml.py`

Responsibilities:

- Emit canonical YAML documents into load-order-friendly folders:

```text
generated/scenariodb/
  00_hw/
  01_external/
  02_definition/
  03_evidence/
  04_decision/
```

### 9.8 `report.py`

Responsibilities:

- Emit import summary.
- List unsupported fields.
- List lossy conversions.
- List missing IP/sensor/display references.
- List viewer-readiness warnings.

## 10. Validation Requirements

Importer validation must be stricter than the current permissive loader.

Required checks:

- Every scenario `config_paths.hw_config` exists.
- Every scenario `config_paths.sensor_config` exists.
- Every `sensor.hw/mode` exists in sensor catalog.
- Every `ip_blocks[*].ip_settings.hw` exists in HW catalog.
- Every task ID is unique within a scenario.
- Every edge `src/dst` references known tasks.
- Every `src_port/dst_port` references an IP module when available.
- Every M2M edge must produce or reference a buffer descriptor.
- Every buffer has format, bitwidth, size, and compression state when known.
- Every generated `pipeline.edge` endpoint exists.
- Every generated `variant.node_configs` node exists in the base scenario.
- Display target exists when scenario includes display/DPU output.

Report levels:

- `error`: cannot safely import.
- `warning`: import can proceed but viewer/simulation fidelity may be reduced.
- `info`: traceability or normalization note.

## 11. Viewer Readiness

For the first viewer pass, generated scenario should include:

- Base `pipeline.nodes`.
- Base `pipeline.edges`.
- Base `pipeline.buffers`.
- `pipeline.architecture_graph` hints.
- `pipeline.task_graph` generated from legacy tasks and edges.
- Optional `pipeline.level1_graph` if enough detail exists.

Minimum useful Level 0:

- Sensor.
- App/Framework/HAL/Kernel placeholders if not present in legacy YAML.
- HW path.
- Memory/buffer summary.
- Display target.

Minimum useful Level 1:

- IP-level detail with crop/scale/rotate badges.
- DMA-related M2M buffers.
- Compression and LLC placement if known.

## 12. Step-Based Implementation Plan

### Step 1: Capability Model Extension

Files:

- `src/scenario_db/models/capability/hw.py`
- `tests/unit/test_capability_models.py`
- demo fixture examples

Changes:

- Add `IpCapabilities.properties: dict[str, Any]`.
- Add optional crop/scale/rotate flags to `SupportedFeatures`.
- Add unit tests for `category: sensor` and `category: display` catalog entries.

Exit criteria:

- Existing unit tests pass.
- New sensor/display catalog YAML validates.

### Step 2: Canonical Sensor And Display Demo Fixtures

Files:

- `demo/fixtures/00_hw/ip-sensor-hp2-projectA.yaml`
- `demo/fixtures/00_hw/ip-display-fhd-panel-projectA.yaml`

Changes:

- Add example sensor category catalog.
- Add example display category catalog.
- Add references from demo project/SoC if needed.

Exit criteria:

- ETL loads demo fixtures.
- API can return sensor/display through capability endpoints.

### Step 3: Legacy Importer Scaffold

Status:

- Step 3A: HW catalog conversion implemented.
- Step 3B: capability model accepts sensor/display catalog categories.
- Step 3C: sensor config and optional display sidecar conversion implemented.
- Step 3D: variant overlay fields preserved by model and ETL mapper.

Files:

- `src/scenario_db/legacy_import/*`
- `tests/unit/test_legacy_import_*.py`

Changes:

- Add CLI that reads legacy paths and emits canonical YAML.
- Start with HW + sensor + display only.

Exit criteria:

- `projectA_hw.yaml` converts into `ip` documents.
- `sensor_config.yaml` converts into `sensor` catalog documents.
- optional display sidecar converts into `display` catalog documents.

### Step 4: Legacy Scenario To Variant Conversion

Prerequisite added before Step 4:

- Step 3D: canonical `Variant` model and ETL mapper must preserve
  `routing_switch`, `topology_patch`, `node_configs`, and `buffer_overrides`.
  Without this, the importer can generate useful YAML but DB load loses the
  variant-specific configuration needed by the Viewer and resolver.

Changes:

- Convert one legacy scenario YAML into:
  - one `scenario.usecase`
  - one variant
  - generated task graph
  - generated buffers
- Generate a small project stub so `scenario.usecase.project_ref` can satisfy
  DB foreign-key loading in an isolated import folder.
- Preserve legacy task IDs as canonical pipeline node IDs.
- Preserve `ip_settings.inputs/outputs`, `tasks`, and `sw_tasks` under
  variant `node_configs`.
- Generate M2M buffer descriptors from edge ports and mirror them to
  variant `buffer_overrides`.

Exit criteria:

- `projectA_FHD30_recording_scenario.yaml` imports.
- Generated `uc-fhd30-recording.yaml` validates with the canonical Usecase model.
- Viewer Level 0 and topology view show the expected path.

### Step 5: Variant Grouping

Changes:

- Group `FHD30/FHD60/UHD30/UHD60` scenario YAMLs into one `camera-recording` scenario.
- Generate one base pipeline and multiple variants.
- Deduplicate common IP topology.
- Use Superset & Switch for optional branches that are structurally present in
  most variants, such as preview/display, codec branch, or SW task branch.
- Use Delta Patch for real topology differences, such as a missing task,
  additional IP, or different producer/consumer edge.
- Store per-variant size/format/mode differences in `size_overrides`,
  `node_configs`, and `buffer_overrides`; avoid duplicating the full scenario.

Exit criteria:

- Viewer can switch variants without duplicating base scenario.
- Read API returns expected `design_conditions` and `size_overrides`.
- Variant inheritance and patch resolution preserve all node/buffer overrides.

### Step 6: Variant Generation From Axes

Changes:

- Add optional `variant_matrix.yaml`.
- Generate variants from resolution/fps/codec/hdr/sensor_mode axes.
- Allow per-axis override rules for size and buffer format.

Exit criteria:

- FHD30/FHD60/UHD30/UHD60 can be generated without copying full scenario YAML.
- Generated variants validate before DB load.

### Step 7: Strict Import Mode

Changes:

- Add strict validation/report to importer.
- Add `--fail-on-warning` option.
- Add JSON report artifact.

Exit criteria:

- Internal import can be reviewed before loading DB.
- Missing IP/sensor/display/edge references are visible.

## 13. Recommended First Commit Scope

The first implementation commit should not attempt full scenario conversion.

Recommended first commit:

- Extend capability model with `properties`.
- Add sensor/display demo fixtures.
- Add unit tests.
- Add legacy importer scaffold with HW/sensor/display conversion only.

Reason:

- This proves category catalog modeling.
- It keeps DB schema stable.
- It avoids mixing catalog conversion and variant grouping complexity in one patch.

## 14. Open Decisions

These should be decided during pilot import:

- Whether display panel should stay `category: display` or split into `display_panel`.
- Whether sensor should remain `ip_catalog` or become a dedicated `sensor_modes` table.
- How to name canonical IP IDs from legacy names.
- Whether legacy scenario files should remain as source of truth or be converted once into canonical YAML.
- Whether generated canonical YAML should be committed, or regenerated in CI/import jobs.

## 15. Practical Recommendation

For the first internal transfer:

1. Keep legacy YAML as the source input.
2. Generate canonical YAML into a separate output folder.
3. Review generated YAML diffs.
4. Load generated YAML into PostgreSQL.
5. Verify API and Viewer.
6. Only after the flow is stable, decide whether to author future scenarios directly in canonical format or keep authoring in legacy compact format.
