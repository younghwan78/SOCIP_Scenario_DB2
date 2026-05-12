# Exploration API Contract

Exploration API는 block 구성이 확정되지 않은 차기 SoC/과제 후보를 빠르게 구성하고, canonical ScenarioDB YAML 및 preview simulation 결과로 검토하기 위한 API이다.

이 API는 기본적으로 DB evidence를 저장하지 않는다. 사용자가 후보를 검토한 뒤 별도 promote/save 흐름을 선택하기 전까지 결과는 preview 데이터로만 취급한다.

## Scope

| Area | Included | Excluded for now |
| --- | --- | --- |
| 예제 조회 | repo 내 `demo/exploration_fixtures` recipe/sweep 목록과 YAML 원문 조회 | 사용자별 예제 저장소 관리 |
| Recipe compile | exploration recipe YAML/dict를 canonical `scenario.usecase` 및 `scenario.import_bundle`로 변환 | DB write/import 자동 적용 |
| Sweep compile | sweep axes를 variant set으로 확장하고 import bundle 생성 | 대용량 비동기 job queue |
| Sweep preview | compiled candidate를 simulation preview로 실행하고 KPI 비교 반환 | evidence persistence, review approval |

## Base Path

All endpoints are mounted below:

```text
/api/v1/exploration
```

## Common Rules

- `source_yaml` 또는 구조화된 `recipe`/`sweep` 중 하나를 입력한다.
- 둘 다 제공되면 `source_yaml`이 우선한다.
- `source_yaml`은 YAML mapping이어야 한다.
- compile/preview 결과는 caller가 복사하거나 dashboard에서 비교할 수 있도록 JSON-compatible payload로 반환한다.
- preview endpoint는 `persisted=false`를 반환하며 evidence DB에 기록하지 않는다.

## Endpoints

### `GET /examples`

Exploration fixture 예제 목록을 반환한다.

Response:

```json
{
  "items": [
    {
      "id": "recipe:camera_crop_scale_m2m",
      "type": "recipe",
      "title": "Camera Crop Scale M2M Exploration",
      "fixture_id": "explore-camera-crop-scale-m2m",
      "path": "demo/exploration_fixtures/recipes/camera_crop_scale_m2m.yaml",
      "scenario_id": "uc-explore-camera-crop-scale",
      "variant_id": "crop-scale-fhd30",
      "tags": ["camera", "exploration"]
    }
  ],
  "total": 1
}
```

### `GET /examples/{example_id}`

Example id는 `recipe:<stem>` 또는 `sweep:<stem>` 형식이다.

Response:

```json
{
  "id": "sweep:camera_fps_format_sweep",
  "type": "sweep",
  "title": "camera-fps-format-sweep",
  "fixture_id": "camera-fps-format-sweep",
  "path": "demo/exploration_fixtures/sweeps/camera_fps_format_sweep.yaml",
  "yaml_text": "id: camera-fps-format-sweep\n...",
  "payload": {}
}
```

### `POST /recipes/compile`

Exploration recipe를 canonical scenario/import bundle로 compile한다.

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

Sweep axes를 candidate variants로 확장하고 import bundle을 반환한다.

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

### `POST /sweeps/preview`

Sweep를 compile한 뒤 simulation을 preview-only로 실행하고 후보 비교를 반환한다.

Request:

```json
{
  "source_yaml": "id: camera-fps-format-sweep\n...",
  "config": {
    "include_timeline": false
  },
  "dvfs_tables": {},
  "include_results": false
}
```

Response:

```json
{
  "persisted": false,
  "baseline_case_id": "explore-fps-30-source_format-raw_bayer_16",
  "cases": [
    {
      "case_id": "explore-fps-30-source_format-raw_bayer_16",
      "scenario_id": "uc-explore-camera-fps-format",
      "variant_id": "explore-fps-30-source_format-raw_bayer_16",
      "axis_values": {"fps": 30, "source_format": "RAW_BAYER_16"},
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

## Error Semantics

| Status | Meaning |
| --- | --- |
| 404 | 예제 id가 존재하지 않음 |
| 422 | YAML parse 실패, schema validation 실패, recipe/sweep 입력 누락 |
| 500 | unexpected server-side failure |

## Dashboard Usage Model

Exploration Dashboard는 이 API를 다음 순서로 사용한다.

1. `GET /examples`로 기본 recipe/sweep 후보를 표시한다.
2. 선택한 예제는 `GET /examples/{example_id}`로 YAML 원문을 가져와 editor에 채운다.
3. 사용자가 `Compile`을 누르면 `/recipes/compile` 또는 `/sweeps/compile`로 canonical YAML을 확인한다.
4. sweep 후보 비교가 필요하면 `/sweeps/preview`를 호출한다.
5. 후보별 상세 결과는 기존 Evidence Dashboard result viewer component를 재사용한다.
6. 저장/promote는 별도 명시 동작으로 분리한다.
