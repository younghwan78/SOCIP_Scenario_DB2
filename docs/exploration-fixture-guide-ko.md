# Exploration Fixture 사용 및 테스트 가이드

이 문서는 `demo/exploration_fixtures`에 추가된 exploration 예제를 설명하고,
각 예제를 어떻게 compile/test/검증하는지 정리합니다.

Exploration fixture는 아직 최종 IP 구성이 정해지지 않은 차기 과제나
architecture exploration 단계에서 빠르게 power/BW/performance를 예측하기
위한 입력 예제입니다. 이 YAML들은 canonical `scenario.usecase`가 아니라,
exploration compiler의 입력입니다.

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

## 핵심 개념

### Recipe

Recipe는 하나의 exploration 후보를 표현합니다.

예를 들어 아직 IP block 이름이 확정되지 않았더라도 다음처럼 표현할 수
있습니다.

```text
sensor/source -> CIN -> core -> COUT
source/buffer -> RDMA -> core -> WDMA
```

Compiler는 recipe를 canonical `scenario.usecase` 문서와
`scenario.import_bundle` payload로 변환합니다.

### Mapping Profile

Mapping profile은 기존 과제의 IP/role simulation 값을 차용하기 위한 매핑입니다.

예:

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

이 정보는 compile 결과의 `node_configs.*.sim.mapping_source`에 남고,
debug trace에서도 borrowed provenance로 확인할 수 있습니다.

### Sweep

Sweep은 하나의 base recipe에서 여러 축을 바꿔 여러 후보를 만드는 burst
exploration입니다.

예:

```yaml
axes:
  - name: fps
    path: source.fps
    values: [30, 60]
  - name: compression
    path: pipeline[0].outputs[0].compression
    values: [COMP_OFF, COMP_SBWC_LOSSLESS]
```

Compiler는 축 조합을 variant 후보로 펼칩니다.

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
source: 4080x2296
byrp0.crop: 3840x2160
gdc0.scale: 1920x1080
gdc0.output_format: YUV420
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
PREVIEW_WDMA   1280x720  YUV420 COMP_OFF
VIDEO_WDMA     1920x1080 YUV420 COMP_SBWC_LOSSLESS
ANALYTICS_WDMA 960x540   YUV422 COMP_OFF LLC enabled
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

## Recipe Compile 방법

예제 recipe를 canonical scenario YAML과 import bundle로 변환합니다.

```powershell
uv run python scripts\compile_exploration_recipe.py `
  demo\exploration_fixtures\recipes\camera_crop_scale_m2m.yaml `
  --output .runlogs\camera_crop_scale_m2m.compiled.yaml `
  --bundle-output .runlogs\camera_crop_scale_m2m.bundle.json
```

확인할 파일:

```text
.runlogs/camera_crop_scale_m2m.compiled.yaml
.runlogs/camera_crop_scale_m2m.bundle.json
```

`compiled.yaml`은 canonical `scenario.usecase` 문서입니다.
`bundle.json`은 Write API의 `scenario.import_bundle` 형태입니다.

## Sweep Compile 방법

```powershell
uv run python scripts\compile_exploration_sweep.py `
  demo\exploration_fixtures\sweeps\camera_fps_format_sweep.yaml `
  --bundle-output .runlogs\camera_fps_format_sweep.bundle.json `
  --cases-output .runlogs\camera_fps_format_sweep.cases.json
```

확인할 파일:

```text
.runlogs/camera_fps_format_sweep.bundle.json
.runlogs/camera_fps_format_sweep.cases.json
```

`cases.json`에는 각 후보의 axis 값과 mapping trace가 들어갑니다.

## 자동 테스트 방법

Exploration fixture만 검증:

```powershell
uv run pytest tests\unit\sim\test_exploration_fixtures.py -q
```

기대 결과:

```text
7 passed
```

Simulation 관련 unit 전체 검증:

```powershell
uv run pytest tests\unit\sim -q
```

현재 기준 기대 결과:

```text
76 passed
```

전체 unit regression:

```powershell
uv run pytest tests\unit -q
```

현재 기준 기대 결과:

```text
431 passed
```

## 테스트가 확인하는 것

`tests/unit/sim/test_exploration_fixtures.py`는 다음을 확인합니다.

- 모든 recipe YAML이 `ExplorationRecipe` schema를 통과하는지
- 모든 sweep YAML이 `ExplorationSweep` schema를 통과하는지
- recipe compile 결과가 `Usecase` model validation을 통과하는지
- compile된 `scenario.import_bundle`이 Write API import validation을 통과하는지
- compiled node config에 `sim.inherit_shape: true`가 포함되는지
- mapping provenance가 `sim.mapping_source`에 남는지
- sweep preview backend가 각 후보를 simulation preview로 실행하는지
- preview 결과가 evidence로 저장되지 않고 `persisted=false` 경계를 유지하는지

## 결과 해석 포인트

### `inherit_shape`

Exploration compiler가 만든 node는 자동으로 다음 값을 갖습니다.

```yaml
sim:
  inherit_shape: true
```

이 값이 있어야 shape propagation 결과가 workload size와 DMA port default에
반영됩니다. 기존 production fixture는 이 값을 자동으로 켜지 않으므로 기존
golden 결과가 바뀌지 않습니다.

### `mapping_source`

각 node의 simulation config에는 다음 정보가 포함됩니다.

```yaml
mapping_source:
  confidence: borrowed
  source_ip_ref: ip-isp-v12
  source_role: byrp
  scale: 1.0
```

이 값은 나중에 debug trace에서 “이 power/ppc 값이 native인지 borrowed인지”를
판단하는 근거가 됩니다.

### Sweep Comparison

`run_exploration_sweep_preview()`는 각 case별 KPI와 baseline 대비 delta를
계산합니다.

주요 비교 값:

- `total_power_mw`
- `core_power_mw`
- `bw_power_mw`
- `total_bw_mbs`
- `hw_time_max_ms`
- `timeline_end_ms`
- `delta_total_power_mw`
- `delta_total_bw_mbs`

이 결과는 아직 DB evidence로 저장되지 않습니다. 사용자가 후보를 선택한 뒤에만
정식 variant 또는 evidence로 승격하는 흐름을 붙이는 것이 다음 단계입니다.

## 현재 한계

현재 exploration fixture와 compiler는 backend foundation 수준입니다.

아직 없는 것:

- FastAPI exploration endpoint
- Streamlit Exploration Workbench UI
- DB에 mapping profile을 독립 catalog로 저장하는 기능
- sweep 결과를 dashboard에서 scatter/table로 비교하는 UI
- 선택한 후보만 variant/evidence로 승격하는 UI flow

즉, 현재 예제는 CLI와 unit test로 검증하는 개발자용 기준 fixture입니다.
서버만 사용하는 사용자를 위해서는 다음 단계에서 API와 dashboard를 붙여야 합니다.
