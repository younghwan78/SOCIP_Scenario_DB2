# Exploration API Contract

Exploration API는 block 구성이 확정되지 않은 차기 SoC/과제 후보를 빠르게 구성하고, canonical ScenarioDB YAML 및 preview simulation 결과로 검토하기 위한 API이다.

이 API는 기본적으로 DB evidence를 저장하지 않는다. 사용자가 후보를 검토한 뒤 별도 import/review/save 흐름을 선택하기 전까지 결과는 preview 데이터로만 취급한다.

## Scope

| Area | Included | Excluded for now |
| --- | --- | --- |
| 예제 조회 | repo 내 `demo/exploration_fixtures` recipe/sweep/template/template_sweep 목록과 YAML 원문 조회 | 사용자별 예제 저장소 관리 |
| Recipe compile | Single Design YAML/dict를 canonical `scenario.usecase` 및 `scenario.import_bundle`로 변환 | DB write/import 자동 적용 |
| Sweep compile | Batch Exploration axes를 variant set으로 확장하고 import bundle 생성 | 대용량 비동기 job queue |
| Chain Template compile | versioned template, compact buffer tuple, compact port link를 canonical scenario로 변환 | template registry DB 저장 |
| Template Sweep compile | versioned template을 axis 조합으로 확장 | template inheritance/patch registry |
| Preview simulation | compiled candidate를 simulation preview로 실행하고 KPI 비교 반환 | evidence persistence, review approval |

## Base Path

All endpoints are mounted below:

```text
/api/v1/exploration
```

## Common Rules

- `source_yaml` 또는 구조화된 `recipe`/`sweep`/`template` 중 하나를 입력한다.
- 둘 다 제공되면 `source_yaml`이 우선한다.
- `source_yaml`은 YAML mapping이어야 한다.
- compile/preview 결과는 caller가 복사하거나 dashboard에서 비교할 수 있도록 JSON-compatible payload로 반환한다.
- preview endpoint는 `persisted=false`를 반환하며 evidence DB에 기록하지 않는다.
- `COMP_OFF`는 `comp_ratio`를 사용하지 않는다. compact tuple에 `1.0`이 들어와도 compiled sim port에는 `comp_ratio`가 남지 않는다.

## Input Types

| UI term | API/schema term | YAML marker | Typical use |
| --- | --- | --- | --- |
| Single Design | recipe | top-level `source` + `pipeline` | 빠른 단일 후보 작성 |
| Batch Exploration | sweep | top-level `base_recipe` + `axes` | 같은 topology의 fps/format/size/compression 조합 비교 |
| Chain Template | template | `kind: scenario.chain_template` | 실제 ISP chain처럼 IP/DMA/buffer가 많은 구조를 compact하게 작성 |
| Template Sweep | template_sweep | `kind: scenario.chain_template_sweep` | versioned template의 buffer/port/IP parameter 조합 비교 |

## Endpoints

### `GET /examples`

Exploration fixture 예제 목록을 반환한다.

`id`는 `{type}:{file_stem}` 형식이며 `type`은 `recipe`, `sweep`, `template`, `template_sweep` 중 하나이다.

Response:

```json
{
  "items": [
    {
      "id": "template:camera_recording_pyramid_v1",
      "type": "template",
      "title": "Camera Recording Pyramid Template",
      "fixture_id": "camera-recording-pyramid",
      "path": "demo/exploration_fixtures/templates/camera_recording_pyramid_v1.yaml",
      "scenario_id": "uc-explore-camera-recording-pyramid",
      "variant_id": "pyramid-fhd30",
      "tags": ["camera", "recording", "pyramid", "compact-template"]
    }
  ],
  "total": 1
}
```

### `GET /examples/{example_id}`

Example id 형식:

```text
recipe:<stem>
sweep:<stem>
template:<stem>
template_sweep:<stem>
```

Response:

```json
{
  "id": "template_sweep:camera_recording_pyramid_full_sbwc_template_sweep",
  "type": "template_sweep",
  "title": "Camera Recording Pyramid Full SBWC Template Sweep",
  "fixture_id": "camera-recording-pyramid-full-sbwc-template-sweep",
  "path": "demo/exploration_fixtures/template_sweeps/camera_recording_pyramid_full_sbwc_template_sweep.yaml",
  "yaml_text": "kind: scenario.chain_template_sweep\n...",
  "payload": {}
}
```

### `POST /recipes/compile`

Single Design을 canonical scenario/import bundle로 compile한다.

Request:

```json
{
  "source_yaml": "id: explore-camera...\nproject_ref: proj-A-exynos2500\n..."
}
```

or:

```json
{
  "recipe": {
    "id": "explore-camera",
    "project_ref": "proj-A-exynos2500",
    "source": {"width": 1920, "height": 1080},
    "pipeline": [{"id": "isp0", "template": "isp_like"}]
  }
}
```

Response:

```json
{
  "persisted": false,
  "scenario": {},
  "import_bundle": {},
  "warnings": [],
  "mapping_trace": []
}
```

### `POST /sweeps/compile`

Batch Exploration axes를 candidate variants로 확장하고 import bundle을 반환한다.

Request:

```json
{
  "source_yaml": "id: camera-fps-format-sweep\nbase_recipe:\n  ...\naxes:\n  ..."
}
```

Response:

```json
{
  "persisted": false,
  "import_bundle": {},
  "cases": [
    {
      "case_id": "explore-fps-30-source_format-raw_bayer_16",
      "scenario_id": "uc-explore-camera-fps-format",
      "variant_id": "explore-fps-30-source_format-raw_bayer_16",
      "axis_values": {"fps": 30, "source_format": "RAW_BAYER_16"},
      "mapping_trace": []
    }
  ],
  "warnings": []
}
```

### `POST /templates/compile`

Versioned Chain Template을 canonical scenario/import bundle로 compile한다.

Request:

```json
{
  "source_yaml": "kind: scenario.chain_template\nid: camera-recording-pyramid\nversion: 1.0.0\n..."
}
```

Response:

```json
{
  "persisted": false,
  "scenario": {},
  "import_bundle": {
    "import_report": {
      "generated": {"chain_template": 1}
    }
  },
  "warnings": [],
  "mapping_trace": []
}
```

### `POST /template-sweeps/compile`

Template Sweep axes를 candidate template set으로 확장하고 import bundle을 반환한다.

Request:

```json
{
  "source_yaml": "kind: scenario.chain_template_sweep\nbase_template:\n  kind: scenario.chain_template\n  ...\naxes:\n  ..."
}
```

Response:

```json
{
  "persisted": false,
  "import_bundle": {
    "import_report": {
      "generated": {"chain_template_sweep_case": 32}
    }
  },
  "cases": [
    {
      "case_id": "pyramid-full-l0-off-l1-off-l2-off-l3-off-g4-off",
      "scenario_id": "uc-explore-camera-recording-pyramid-full-template-sweep-pyramid-full-l0-off-l1-off-l2-off-l3-off-g4-off",
      "variant_id": "pyramid-full-l0-off-l1-off-l2-off-l3-off-g4-off",
      "axis_values": {"l0": [0, 0, 2400, 1350, "YUV420", 10, "COMP_OFF", 1.0]},
      "template_ref": "camera-recording-pyramid@1.0.0"
    }
  ],
  "warnings": []
}
```

### `POST /sweeps/preview`

Batch Exploration을 compile한 뒤 simulation을 preview-only로 실행하고 후보 비교를 반환한다.

### `POST /templates/preview`

Chain Template을 1-case preview set처럼 simulation한다. Workbench의 Single Design/Template preview detail 재사용을 위해 response shape는 sweep preview와 같다.

### `POST /template-sweeps/preview`

Template Sweep을 compile한 뒤 각 candidate를 preview simulation으로 실행하고 KPI 비교를 반환한다.

Preview request 공통:

```json
{
  "source_yaml": "kind: scenario.chain_template_sweep\n...",
  "config": {
    "include_timeline": false,
    "timeline_frame_count": 4,
    "debug_trace": true,
    "debug_trace_level": "formula"
  },
  "dvfs_tables": {},
  "include_results": true
}
```

Preview response 공통:

```json
{
  "persisted": false,
  "baseline_case_id": "pyramid-full-l0-off-l1-off-l2-off-l3-off-g4-off",
  "cases": [
    {
      "case_id": "pyramid-full-l0-off-l1-off-l2-off-l3-off-g4-off",
      "scenario_id": "uc-explore-camera-recording-pyramid-full-template-sweep-pyramid-full-l0-off-l1-off-l2-off-l3-off-g4-off",
      "variant_id": "pyramid-full-l0-off-l1-off-l2-off-l3-off-g4-off",
      "axis_values": {"l0": [0, 0, 2400, 1350, "YUV420", 10, "COMP_OFF", 1.0]},
      "kpi": {
        "total_power_mw": 10.0,
        "total_bw_mbs": 200.0
      },
      "delta_from_baseline": {
        "total_power_mw": 0.0
      },
      "warnings": [],
      "feasible": true,
      "infeasible_reason": null,
      "result": null
    }
  ],
  "comparison": [],
  "import_bundle": {}
}
```

## Chain Template Authoring Notes

### Compact buffer tuple

`buffer_columns` defines how tuple values map to explicit buffer fields.

```yaml
buffer_columns: [x, y, width, height, format, bitwidth, compression, comp_ratio]
buffers:
  L0: [0, 0, 2400, 1350, YUV420, 10, COMP_SBWC_LOSSLESS, 0.5]
  L1: {derive_from: L0, scale: 0.5}
```

`derive_from` copies format/bitwidth/compression from the referenced buffer unless overridden.

### Compact port link

```yaml
links:
  - "sensor_src:COUT -> csis:CIN | OTF"
  - "mlsc:WDMA0 -> L0 | M2M"
  - "L0 -> mtnr:RDMA0 | M2M"
```

Node-to-node links become direct scenario edges. Node-to-buffer and buffer-to-node pairs become an M2M edge with `buffer`.

## Error Semantics

| Status | Meaning |
| --- | --- |
| 404 | 예제 id가 존재하지 않음 |
| 422 | YAML parse 실패, schema validation 실패, recipe/sweep/template 입력 누락 |
| 500 | unexpected server-side failure |

## Dashboard Usage Model

Exploration Workbench는 이 API를 다음 순서로 사용한다.

1. `GET /examples`로 기본 recipe/sweep/template/template_sweep 후보를 표시한다.
2. 선택한 예제는 `GET /examples/{example_id}`로 YAML 원문을 가져와 editor에 채운다.
3. 사용자가 `Compile`을 누르면 입력 종류에 맞는 compile endpoint로 canonical YAML/import bundle을 확인한다.
4. 후보 비교가 필요하면 입력 종류에 맞는 preview endpoint를 호출한다.
5. 후보별 상세 결과는 기존 Evidence Dashboard result viewer component를 재사용한다.
6. 저장/promote는 별도 명시 동작으로 분리한다.
