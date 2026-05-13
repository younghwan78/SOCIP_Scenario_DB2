# Exploration Fixture 사용 및 테스트 가이드

이 문서는 `demo/exploration_fixtures`에 들어 있는 architecture exploration 예제를 설명하고,
CLI/API/Streamlit Workbench에서 어떻게 compile, simulation preview, 후보 비교를 하는지 정리합니다.

Exploration fixture는 아직 최종 IP 구성이 확정되지 않은 차기 과제나 초기 SoC architecture exploration 단계에서
대략적인 power, BW, performance를 빠르게 비교하기 위한 입력입니다. 이 YAML은 production용 canonical
`scenario.usecase`가 아니라 exploration compiler의 입력입니다.

## 현재 지원 범위

| 구분 | 현재 지원 | 아직 남은 항목 |
| --- | --- | --- |
| 예제 fixture | repo 내 Single Design/Batch Exploration YAML 예제 | 사용자별 예제 저장소 |
| CLI compile | exploration YAML을 canonical scenario/import bundle로 변환 | CLI에서 DB apply까지 자동 수행 |
| API | 예제 조회, compile, batch preview simulation | promote/save API |
| Streamlit | YAML load/edit, compile, preview simulation, 후보 비교, topology 확인 | 선택 후보를 정식 variant/evidence로 승격 |
| Simulation | preview-only, evidence DB 미저장 | 승인된 후보만 evidence로 저장하는 workflow |

## 폴더 구조

```text
demo/exploration_fixtures/
  README.md
  recipes/
    camera_otf_chain_fhd30.yaml
    camera_crop_scale_m2m.yaml
    camera_multi_output_fanout.yaml
    codec_display_path.yaml
  sweeps/
    camera_fps_format_sweep.yaml
    camera_scale_compression_sweep.yaml
```

## 용어

### Single Design

Workbench에서 보이는 `Single Design`은 하나의 exploration 후보를 의미합니다.
내부 schema/CLI 이름은 기존 호환성을 위해 `recipe`를 유지합니다.

예를 들어 IP block 이름이 아직 확정되지 않았더라도 다음처럼 입력할 수 있습니다.

```text
sensor/source -> CIN -> core -> COUT
source/buffer -> RDMA -> core -> WDMA
```

Compiler는 이 입력을 canonical `scenario.usecase` 문서와 `scenario.import_bundle` payload로 변환합니다.
Workbench의 `Run Simulation`은 Single Design도 1개 후보짜리 Batch Exploration처럼 감싸서 preview simulation을 실행합니다.

### Batch Exploration

Workbench에서 보이는 `Batch Exploration`은 하나의 base design에서 여러 축을 바꿔 후보 set을 만드는 burst exploration입니다.
내부 schema/CLI 이름은 `sweep`입니다.

예:

```yaml
axes:
  - name: fps
    path: base_recipe.source.fps
    values: [30, 60]
  - name: compression
    path: base_recipe.pipeline[0].outputs[0].compression
    values: [COMP_OFF, COMP_SBWC_LOSSLESS]
```

Compiler는 축 조합을 variant 후보로 펼치고, preview simulation은 후보별 KPI와 baseline 대비 delta를 반환합니다.

### Mapping Profile

Mapping profile은 차기 과제의 unit power, PPC, DVFS 정보가 아직 없을 때 기존 과제의 IP/role 값을 차용하기 위한 매핑입니다.

```yaml
mapping_profile:
  role_mappings:
    byrp_like:
      source_ip_ref: ip-isp-v12
      target_ip_ref: ip-isp-v12
      source_role: byrp
      target_role: byrp
      confidence: borrowed
      ip_params:
        hw_name: BYRP
        ppc: 4
        unit_power_mw_mp: 4.34
        vdd: VDD_CAM
        dvfs_group: CAM
```

이 정보는 compile 결과의 `node_configs.*.sim.mapping_source`에 남고, debug trace에서도 borrowed provenance로 확인할 수 있습니다.

## Streamlit Workbench 사용

API와 dashboard를 실행한 뒤 다음 페이지를 엽니다.

```text
http://127.0.0.1:18502/Exploration_Workbench
```

기본 흐름:

1. 왼쪽 `Exploration Context`에서 API base를 확인합니다.
2. `Example`에서 기본 예제를 고르거나, `Upload Exploration YAML`로 YAML 파일을 올립니다.
3. `Load selected example` 또는 `Load uploaded YAML`을 누르면 `Exploration YAML` editor에 내용이 들어갑니다.
4. `Start blank YAML`은 빈 editor에서 직접 YAML을 작성할 때 사용합니다.
5. editor에서 YAML을 수정한 뒤 `Compile`로 canonical scenario/import bundle 생성을 확인합니다.
6. `Run Simulation`으로 preview-only simulation을 실행합니다.
7. `Candidate Comparison`에서 후보별 KPI와 delta를 비교합니다.
8. `Selected Candidate Detail`에서 기존 Evidence Dashboard viewer component로 후보 상세 결과를 확인합니다.

Workbench는 YAML top-level 구조를 보고 자동으로 입력 종류를 판단합니다.

| YAML 형태 | 판단 |
| --- | --- |
| `base_recipe`가 있음 | Batch Exploration |
| `source`와 `pipeline`이 있음 | Single Design |

`Hide Exploration YAML`을 누르면 입력 panel을 접고 결과 영역을 넓게 볼 수 있습니다. 다시 수정하거나 다른 simulation을 실행하려면
`Show Exploration YAML`로 펼치면 됩니다.

### Compile Result 해석

Workbench의 `Compile Result`는 다음 값을 보여줍니다.

| 항목 | 의미 |
| --- | --- |
| `Saved to DB` | compile 단계가 DB에 저장했는지 여부입니다. 현재 Workbench compile은 정상적으로 `no`가 나와야 합니다. |
| `Generated Documents` | canonical scenario/import bundle에 포함된 문서 수입니다. |
| `Candidates` | Batch Exploration에서 축 조합으로 생성된 후보 수입니다. Single Design compile은 0 또는 1개 후보처럼 표시될 수 있습니다. |
| `Warnings` | borrowed mapping, 미정 capability 등 검토가 필요한 경고 수입니다. |

현재 Workbench는 preview-first 정책입니다. `Run Simulation` 결과도 `persisted=false`이며 evidence DB에 저장되지 않습니다.
선택 후보를 정식 variant/evidence로 승격하는 promote/save flow는 다음 단계 항목입니다.

### Error Line/Context

YAML parse error는 가능한 경우 line/column과 주변 YAML context를 함께 보여줍니다.
Schema validation error는 `base_recipe`, `source`, `pipeline` 같은 누락 field의 위치를 top-level key 기준으로 추정해 hint를 표시합니다.

예:

```text
Compile failed: API returned HTTP 422
Hint: Batch Exploration YAML needs top-level base_recipe.
Possible YAML location: around line 1
```

정확한 column 단위 schema location은 Pydantic validation이 YAML 원문 line 정보를 직접 보존하지 않기 때문에 제한적입니다.
대신 Workbench가 YAML key 위치를 찾아 가장 가까운 line context를 표시합니다.

## Topology / Port Flow 확인

Workbench의 `Topology` tab은 compile된 canonical graph를 기반으로 topology를 보여줍니다.

중요한 것은 단순 IP 순서가 아니라 어떤 port/DMA가 어떤 edge와 buffer로 이어지는지입니다.
그래서 `Port Flow`는 다음 형태로 표시합니다.

```text
sensor_src.COUT -- OTF --> csis0.CIN
byrp0.YUV_WDMA -- M2M write --> buf_yuv -- M2M read --> gdc0.YUV_RDMA
gdc0.DISPLAY_COUT -- OTF --> dpu0.CIN
```

`Buffer Usage` table은 buffer별 writer/reader와 size, format, compression을 보여줍니다.
M2M/vOTF path의 DMA 연결을 빠르게 디버깅할 때 이 tab을 먼저 확인하는 것이 좋습니다.

## API 사용

Exploration API는 다음 base path 아래에 있습니다.

```text
http://127.0.0.1:18000/api/v1/exploration
```

주요 endpoint:

| Method | Path | 용도 |
| --- | --- | --- |
| `GET` | `/examples` | repo 내 기본 예제 목록 조회 |
| `GET` | `/examples/{example_id}` | 예제 YAML 원문 조회 |
| `POST` | `/recipes/compile` | Single Design compile |
| `POST` | `/sweeps/compile` | Batch Exploration compile |
| `POST` | `/sweeps/preview` | Batch Exploration preview simulation |

PowerShell 예:

```powershell
$example = Invoke-RestMethod `
  http://127.0.0.1:18000/api/v1/exploration/examples/sweep:camera_fps_format_sweep

$payload = @{
  source_yaml = $example.yaml_text
  include_results = $true
  config = @{
    include_timeline = $false
    timeline_frames = 4
    debug_trace = $true
  }
} | ConvertTo-Json -Depth 100

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:18000/api/v1/exploration/sweeps/preview `
  -ContentType "application/json" `
  -Body $payload
```

## CLI 사용

CLI는 개발자나 server-side batch 검증용입니다. 서버 UI만 사용하는 사용자는 Workbench에서 같은 흐름을 수행할 수 있습니다.

### Single Design Compile

```powershell
uv run python scripts\compile_exploration_recipe.py `
  demo\exploration_fixtures\recipes\camera_crop_scale_m2m.yaml `
  --output .runlogs\camera_crop_scale_m2m.compiled.yaml `
  --bundle-output .runlogs\camera_crop_scale_m2m.bundle.json
```

생성 파일:

```text
.runlogs/camera_crop_scale_m2m.compiled.yaml
.runlogs/camera_crop_scale_m2m.bundle.json
```

`compiled.yaml`은 canonical `scenario.usecase` 문서이고, `bundle.json`은 Write API의
`scenario.import_bundle` 형태입니다.

### Batch Exploration Compile

```powershell
uv run python scripts\compile_exploration_sweep.py `
  demo\exploration_fixtures\sweeps\camera_fps_format_sweep.yaml `
  --bundle-output .runlogs\camera_fps_format_sweep.bundle.json `
  --cases-output .runlogs\camera_fps_format_sweep.cases.json
```

생성 파일:

```text
.runlogs/camera_fps_format_sweep.bundle.json
.runlogs/camera_fps_format_sweep.cases.json
```

`cases.json`에는 각 후보의 axis 값과 mapping trace가 들어갑니다.

## 예제별 설명

### 1. `camera_otf_chain_fhd30.yaml`

목적:

- sensor source에서 시작하는 OTF chain 예제
- CSIS-like block과 ISP-like block을 OTF로 연결
- source shape가 downstream으로 전달되는지 확인
- 기존 과제 값을 borrowed mapping으로 사용하는 예제

주요 구조:

```text
sensor_src -> csis0 -> isp_front
```

적합한 용도:

- 초기 camera front-end OTF path power/clock 대략 추정
- sensor size 변경이 전체 OTF chain에 어떻게 반영되는지 확인

### 2. `camera_crop_scale_m2m.yaml`

목적:

- wide sensor source에서 crop 후 scale down하는 예제
- BYRP-like block에서 crop
- GDC-like block에서 FHD scale down 및 WDMA 출력
- crop/scale이 sensor size를 끝까지 그대로 전달하지 않도록 검증

주요 구조:

```text
sensor_src -> byrp0 -> gdc0
```

주요 조건:

```yaml
source:
  width: 4080
  height: 2296
pipeline:
  - id: byrp0
    crop: {width: 3840, height: 2160}
  - id: gdc0
    scale: {width: 1920, height: 1080}
    outputs:
      - format: YUV420
```

적합한 용도:

- camera recording에서 sensor crop과 video output size 차이를 검토
- WDMA BW가 scale output 기준으로 계산되는지 확인

### 3. `camera_multi_output_fanout.yaml`

목적:

- 하나의 IP가 여러 output port를 갖는 경우 검증
- port별 size/format/compression이 다르게 적용되는지 확인

주요 output:

```text
PREVIEW_WDMA    1280x720   YUV420   COMP_OFF
VIDEO_WDMA      1920x1080  YUV420   COMP_SBWC_LOSSLESS
ANALYTICS_WDMA   960x540   YUV422   COMP_OFF, LLC enabled
```

적합한 용도:

- camera preview/video/analytics 동시 output
- multi-output DMA BW와 BW power 비교

### 4. `codec_display_path.yaml`

목적:

- camera가 아닌 video playback/display 계열 예제
- compressed source buffer에서 MFC decode 후 DPU/display로 전달
- RDMA/WDMA/COUT style port 사용

주요 구조:

```text
compressed_src -> mfc_dec -> dpu0
```

적합한 용도:

- codec/display path exploration
- source가 sensor가 아닌 buffer인 경우 검증

### 5. `camera_fps_format_sweep.yaml`

목적:

- fps와 source format을 burst set으로 변경
- 같은 topology에서 여러 variant 후보를 생성

축:

```text
fps: 30, 60
source_format: RAW_BAYER_16, RAW_BAYER_12
```

생성 후보 수:

```text
2 x 2 = 4 variants
```

### 6. `camera_scale_compression_sweep.yaml`

목적:

- scale target과 output compression 조합 비교
- output size/BW/power 변화 확인

축:

```text
scale_width: 1920, 2560
scale_height: 1080, 1440
compression: COMP_OFF, COMP_SBWC_LOSSLESS
```

생성 후보 수:

```text
2 x 2 x 2 = 8 variants
```

## 결과 해석 포인트

### `inherit_shape`

Exploration compiler가 만든 node는 자동으로 다음 값을 갖습니다.

```yaml
sim:
  inherit_shape: true
```

이 값이 있어야 shape propagation 결과가 workload size와 DMA port default에 반영됩니다.
기존 production fixture는 이 값을 자동으로 켜지 않으므로 기존 golden 결과가 바뀌지 않습니다.

### Crop / Scale

`inherit_shape`는 sensor size를 무조건 pipeline 끝까지 복사한다는 의미가 아닙니다.
중간 block에 `crop`이나 `scale`이 있으면 그 block 이후의 workload/DMA size는 변환된 shape를 사용합니다.

예:

```text
sensor 4080x2296 -> crop 3840x2160 -> scale 1920x1080 -> WDMA 1920x1080
```

### `mapping_source`

각 node의 simulation config에는 다음 정보가 포함됩니다.

```yaml
mapping_source:
  confidence: borrowed
  source_ip_ref: ip-isp-v12
  source_role: byrp
  scale: 1.0
```

이 값은 debug trace에서 “이 power/PPC/DVFS 값이 native인지 borrowed인지”를 판단하는 근거가 됩니다.

### Candidate Comparison

Preview simulation은 각 case별 KPI와 baseline 대비 delta를 계산합니다.

주요 비교 값:

- `total_power_mw`
- `core_power_mw`
- `bw_power_mw`
- `total_bw_mbs`
- `hw_time_max_ms`
- `timeline_end_ms`
- `delta_total_power_mw`
- `delta_total_bw_mbs`

현재 결과는 DB evidence로 저장되지 않습니다. 후보를 검토한 뒤 정식 variant/evidence로 승격하는 흐름은 별도 구현 대상입니다.

## 자동 테스트 방법

Exploration fixture와 API contract 검증:

```powershell
uv run pytest tests\unit\sim\test_exploration_fixtures.py tests\unit\api\test_exploration.py -q
```

현재 기준 기대 결과:

```text
14 passed
```

Exploration Workbench contract 검증:

```powershell
uv run pytest tests\unit\dashboard\test_exploration_workbench.py -q
```

현재 기준 기대 결과:

```text
9 passed
```

Dashboard unit regression:

```powershell
uv run pytest tests\unit\dashboard -q
```

현재 기준 기대 결과:

```text
33 passed
```

전체 unit regression:

```powershell
uv run pytest tests\unit -q
```

현재 기준 기대 결과:

```text
447 passed
```

## 테스트가 확인하는 것

`tests/unit/sim/test_exploration_fixtures.py`는 다음을 확인합니다.

- 모든 Single Design YAML이 `ExplorationRecipe` schema를 통과하는지
- 모든 Batch Exploration YAML이 `ExplorationSweep` schema를 통과하는지
- compile 결과가 `Usecase` model validation을 통과하는지
- compile된 `scenario.import_bundle`이 Write API import validation을 통과하는지
- compiled node config에 `sim.inherit_shape: true`가 포함되는지
- mapping provenance가 `sim.mapping_source`에 남는지
- Batch Exploration preview backend가 각 후보를 simulation preview로 실행하는지
- preview 결과가 evidence로 저장되지 않고 `persisted=false` 경계를 유지하는지

`tests/unit/api/test_exploration.py`는 다음을 확인합니다.

- 예제 목록/detail API contract
- Single Design compile endpoint
- Batch Exploration compile endpoint
- Batch Exploration preview endpoint
- 404/422 error boundary

`tests/unit/dashboard/test_exploration_workbench.py`는 다음을 확인합니다.

- Workbench page와 Home navigation wiring
- Exploration API client endpoint path
- `Single Design`, `Batch Exploration`, `Run Simulation` 문구
- upload/blank editor, hide/show input panel
- error detail formatting과 line/context hint
- topology `Port Flow` 표시

## 운영상 주의점

- Exploration API/Workbench는 현재 preview-only입니다.
- Workbench에서 `Saved to DB: no`, simulation result의 `persisted=false`가 정상입니다.
- 후보를 정식 evidence로 저장하려면 별도 confirm/promote flow가 필요합니다.
- borrowed mapping은 초기 exploration에는 유용하지만, 과제 진행 중 native unit power/PPC/DVFS가 확보되면 fixture contract/readiness rule로 교체해야 합니다.
- server 사용자도 Workbench에서 YAML upload 또는 paste로 사용할 수 있으므로 local CLI 환경이 필수는 아닙니다.

## 다음 개선 후보

1. 선택 후보를 정식 variant/evidence로 승격하는 promote/save API와 UI.
2. mapping profile을 독립 catalog로 저장하고 SoC/과제별로 선택하는 기능.
3. Workbench에서 candidate 간 power/BW/timing scatter plot과 Pareto filtering.
4. Topology를 port-flow text와 함께 간단한 graph view로 표시.
5. 사용자별 exploration YAML 저장소와 revision 관리.
