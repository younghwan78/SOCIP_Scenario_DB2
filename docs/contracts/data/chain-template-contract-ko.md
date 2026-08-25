# Chain Template Contract

이 문서는 복잡한 SoC camera/ISP chain을 간결하게 작성하기 위한
`scenario.chain_template` YAML 계약을 설명한다. 목표는 사람이 쓰는 YAML은
짧게 유지하고, compiler 내부에서는 항상 명시적인 canonical scenario로
정규화하는 것이다.

## 용도

실제 과제의 camera chain은 ISP role과 DMA가 많다. 예를 들어 다음과 같은
구조는 일반 `recipe.pipeline`으로 직접 쓰면 YAML이 길어지고 실수하기 쉽다.

```text
sensor -> CSIS -> PDP
CSIS:WDMA_3AA -> B_3AA -> BYRP:RDMA_3AA
BYRP -> RGBP -> YUVP -> MLSC
MLSC:WDMA0..4 -> L0/L1/L2/L3/G4 -> MTNR:RDMA0..4
MTNR -> MSNR -> MCSC
MCSC:WDMA0 -> DISPLAY_OUT -> DPU
MCSC:WDMA1 -> CODEC_OUT -> CODEC
```

Chain template은 이런 topology를 versioned template으로 관리하고,
simulation 실행 전 canonical `scenario.usecase` 문서로 컴파일한다.

## Versioning

Template은 `id + version` 조합으로 관리한다.

```yaml
kind: scenario.chain_template
id: camera-recording-pyramid
version: 1.0.0
schema_version: 1
```

원칙:

- `id + version`은 재현성 단위다. 같은 version의 topology 의미는 바꾸지 않는다.
- 사소한 description/metadata 변경은 patch version을 올린다.
- node, buffer, link 의미가 바뀌면 minor 또는 major version을 올린다.
- compiler 결과에는 `template_ref`, `template_schema_version`,
  `template_normalized_hash`가 variant design condition에 저장된다.

## Compact Buffer Syntax

긴 buffer mapping 대신 tuple 형태를 사용할 수 있다.

```yaml
buffer_columns: [x, y, width, height, format, bitwidth, compression, comp_ratio]
buffers:
  L0: [0, 0, 2400, 1350, YUV420, 10, COMP_SBWC_LOSSLESS, 0.5]
  L1: {derive_from: L0, scale: 0.5}
  DISPLAY_OUT: [0, 0, 1920, 1080, YUV420, 8, COMP_OFF, 1.0]
```

정규화 결과:

```yaml
L0:
  roi: [0, 0, 2400, 1350]
  width: 2400
  height: 1350
  format: YUV420
  bitwidth: 10
  compression: COMP_SBWC_LOSSLESS
  comp_ratio: 0.5
```

`COMP_OFF`, `off`, `disable` 계열 compression은 `comp_ratio`가 있어도 무시된다.
즉 compact tuple에서 default column을 유지하기 위해 `1.0`을 써도 canonical
buffer에는 의미 있는 compression ratio로 남기지 않는다.

## Compact Link Syntax

Port-level 연결은 문자열로 짧게 표현할 수 있다.

```yaml
links:
  - "sensor_src:COUT -> csis:CIN | OTF"
  - "csis:WDMA_3AA -> B_3AA | M2M"
  - "B_3AA -> byrp:RDMA_3AA | M2M"
  - "byrp:COUT -> rgbp:CIN | OTF"
```

Compiler는 buffer를 경유하는 write/read pair를 canonical scenario edge로
변환한다.

```yaml
pipeline:
  edges:
    - from: csis
      to: byrp
      type: M2M
      buffer: B_3AA
```

동시에 node config에는 실제 DMA port가 남는다.

```yaml
node_configs:
  csis:
    sim:
      outputs:
        - port: WDMA_3AA
          port_type: DMA_WRITE
          width: 4080
          height: 2296
  byrp:
    sim:
      inputs:
        - port: RDMA_3AA
          port_type: DMA_READ
          width: 4080
          height: 2296
```

## Mapping Profile

차기 과제처럼 native unit power/PPC/DVFS가 아직 없으면 template 안에
`mapping_profile`을 넣어 이전 과제 값을 명시적으로 빌려 쓸 수 있다.

```yaml
mapping_profile:
  id: map-template-from-projectA-camera
  source_project_ref: proj-A-exynos2500
  target_soc_ref: soc-exynos2500
  role_mappings:
    byrp_like:
      source_ip_ref: ip-isp-v12
      target_ip_ref: ip-isp-v12
      source_role: byrp
      target_role: byrp
      confidence: borrowed
      ip_params:
        hw_name: ISP
        ppc: 4
        unit_power_mw_mp: 9.92
        vdd: VDD_CAM
        dvfs_group: CAM
```

Borrowed 값은 native SoC 측정값처럼 조용히 병합하지 않고, compile result의
`mapping_trace`와 simulation debug trace에서 provenance로 확인할 수 있어야 한다.

## Template Sweep

복잡한 topology는 그대로 두고 buffer compression, size, format, IP parameter만
바꿔 비교하려면 `scenario.chain_template_sweep`을 사용한다.

```yaml
kind: scenario.chain_template_sweep
id: camera-recording-pyramid-sbwc-template-sweep
base_template:
  kind: scenario.chain_template
  id: camera-recording-pyramid
  version: 1.0.0
  schema_version: 1
  project_ref: proj-A-exynos2500
  source:
    width: 4080
    height: 2296
  buffers:
    L0: [0, 0, 2400, 1350, YUV420, 10, COMP_OFF, 1.0]
  blocks:
    - {id: mlsc, template: mlsc_like, ip_ref: ip-isp-v12}
    - {id: mtnr, template: mtnr_like, ip_ref: ip-isp-v12}
  links:
    - "mlsc:WDMA0 -> L0 | M2M"
    - "L0 -> mtnr:RDMA0 | M2M"
axes:
  - name: l0
    path: buffers.L0
    values:
      - {label: "off", value: [0, 0, 2400, 1350, YUV420, 10, COMP_OFF, 1.0]}
      - {label: sbwc, value: [0, 0, 2400, 1350, YUV420, 10, COMP_SBWC_LOSSLESS, 0.5]}
```

현재 구현은 후보별로 scenario document를 분리한다. 이는 후보마다
`pipeline.buffers`가 달라질 수 있기 때문이다. 나중에 pipeline이 완전히 같은
case에 한해서 variant merge 최적화를 추가할 수 있다.

YAML parser에 따라 unquoted `off`가 boolean `false`로 해석될 수 있으므로
axis label에는 `"off"`처럼 quote를 붙인다.

## 실행 예

Template fixture compile:

```powershell
uv run pytest tests\unit\sim\test_chain_templates.py -q
uv run pytest tests\unit\sim\test_exploration_fixtures.py::test_exploration_chain_template_fixtures_compile_to_valid_scenarios -q
uv run pytest tests\unit\sim\test_exploration_fixtures.py::test_exploration_chain_template_sweep_fixtures_compile_and_preview -q
```

API endpoint:

```text
POST /api/v1/exploration/templates/compile
POST /api/v1/exploration/templates/preview
POST /api/v1/exploration/template-sweeps/compile
POST /api/v1/exploration/template-sweeps/preview
```

Streamlit Exploration Workbench에서는 `template:` 예제를 불러오면
`Chain Template` input type으로 인식하고 compile/run preview를 수행한다.
