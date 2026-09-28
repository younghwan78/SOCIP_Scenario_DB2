# Exynos2700 (SM-S957B) data 수정 가이드

사내에서 Exynos2700의 IP, scenario, sensor 정보를 바꾸는 방법을 정리한다.
Exynos2700 authoring은 **eject된 root 과제**다. 2600에서 상속받던 모든 문서가 완전한 파일로 풀려 있으므로, 필요한 파일을 열어 해당 값만 고치면 된다.
공통 개념(compile, sync, knob)은 [authoring-layers-guide-ko.md](authoring-layers-guide-ko.md)를 참고한다.

---

## 0. 원칙과 파일 위치

- `db_Exynos2700_SM-S957B/`의 `00_hw`, `00_sensor`, `01_sw`, `02_definition`은 **생성물**이다. 직접 고치면 `dev_up`이 덮어쓴다.
- 직접 고칠 곳은 `authoring/`과 `db_Exynos2700_SM-S957B/measurements/`(실측 입력) 두 곳뿐이다.

| 무엇을 | 파일 |
|---|---|
| IP (clock, PPC, unit power, mode, DMA port, compression) | `authoring/platforms/exynos2700/docs/00_hw/ip-<name>-s5e9975.yaml` |
| SoC (compression ratio, IP 목록) | `authoring/platforms/exynos2700/docs/00_hw/soc-exynos2700.yaml` |
| DVFS table | `authoring/platforms/exynos2700/docs/00_hw/dvfs-exynos2700-*.yaml` |
| sensor timing / catalog / lineup | `authoring/platforms/exynos2700/docs/00_sensor/{timing-*.yaml, m2s/sensor-*.yaml, board-lineup-*.yaml}` |
| SW profile | `authoring/platforms/exynos2700/docs/01_sw/*.yaml` |
| 과제 문서 (board, 기본 SW profile) | `authoring/projects/sm-s957b/project.yaml`의 `document:` |
| 과제 sim 설정 | `authoring/projects/sm-s957b/docs/**/simcfg-proj-sm-s957b-v1.yaml` |
| scenario 본문 (pipeline node/edge/buffer, 기본 anchor) | `authoring/projects/sm-s957b/scenarios/uc-cam-recording-e2700/scenario.yaml` |
| variant (조건, EIS, routing, node 설정, size) | 같은 폴더의 `variants.yaml` |
| node → size anchor 연결, 파생 anchor | `sizes.yaml` |
| SW task timing (기본값 / 실측) | `sw_timing.yaml` / `sw_timing.measured.yaml` |
| arch knob, power option | `knobs.yaml` |
| 실측 power / BW / latency | `db_Exynos2700_SM-S957B/measurements/<variant>/` (수정할 때마다 `provenance.revision` +1) |

**파일 찾기**
- 파일 이름에는 2600 이름이 남아 있을 수 있다 (예: `timing-s5kgng.yaml`). 문서의 식별자는 파일 안의 `id:`(`...-s5e9975`)다.
- `grep -rl "id: ip-mfc-s5e9975" authoring/platforms/exynos2700`로 찾는다.

**2600과의 관계**
- 2600을 고쳐도 2700에는 **자동 반영되지 않는다**.
- eject 당시 2600 내용의 hash가 `projects/sm-s957b/ejected-from.yaml`에 기록되어 있다. 이후 2600에서 바뀐 부분은 §7의 `parent-diff`로 확인하고, 필요한 것만 2700 파일에 옮긴다.

---

## 1. 작업 절차 (사내 Ubuntu, bash)

```bash
cd <repo>/implementation

# 1) 결과 미리 보기 (DB 폴더는 건드리지 않는다)
uv run python -m scenario_db.authoring compile sm-s957b --out output/preview
uv run python -m scenario_db.authoring sync sm-s957b --fixture db_Exynos2700_SM-S957B --to fixture --dry-run

# 2) HW / SW / topology / size를 바꿨으면 simulation evidence를 재생성한다 (dev_up이 하지 않는다)
uv run python scripts/generate_simulation_evidence.py db_Exynos2700_SM-S957B uc-cam-recording-e2700

# 3) DB 반영: rename → retire → ETL 2600 → [sync → 실측 import → ETL] 2700
scripts/dev_down.sh && scripts/dev_up.sh --no-ui          # 기존 PostgreSQL이면 --no-docker 추가

# 4) 검증
uv run --group dev pytest -q tests/unit/authoring tests/unit/test_exynos2700_db_contract.py
```

- Windows PC에서는 3)을 `powershell -ExecutionPolicy Bypass -File scripts\dev_up.ps1 -NoUi`로 실행한다.
- 서버 준비는 [Linux 실행 가이드](../../operations/linux-server-guide-ko.md)를 참고한다.
- 2)를 빠뜨리면 예측 column과 timing diagram이 예전 값으로 남는다. stale test가 이를 잡는다.
- 입력이 바뀌었으므로 **조합 탐색을 다시 실행하고 예측을 재등록**한다. 예측 현황의 변경 원인이 수정의 효과를 보여 준다.

---

## 2. IP 속성

### 2.1 unit power / PPC / clock / idc

```yaml
# authoring/platforms/exynos2700/docs/00_hw/ip-mcsc-is-v15-s5e9975.yaml (해당 부분만 수정)
capabilities:
  sim:
    source: exynos2700_arch_rev1          # 출처는 반드시 남긴다 (report / UI의 "가정" 표시)
    source_note: 2700 MCSC spec v0.9, power = PTPX 2026-10
    modes:
      Normal:
        unit_power_mw_mp: 1.2             # 1.5 → 1.2
        idc: 0.0
        ppc: 8.0                          # 4.0 → 8.0
        vdd: VDD_CAM
        dvfs_group: CAM
```

- IP power는 `unit_power_mw_mp · MP · (V/710mV)² · (fps/30)`로 계산한다.
- 요구 clock은 `처리 pixel / ppc`로 계산한다.
- mode별 max clock은 `operating_modes[].max_clock_mhz`에 둔다.

### 2.2 mode 추가 / mode별 unit power

```yaml
capabilities:
  operating_modes:
  - {id: Normal}
  - {id: SBWC}
  - {id: HDR10P}
  - {id: LowPower, max_clock_mhz: 533}    # 추가
  sim:
    modes:
      Normal: {...}
      LowPower:                           # 추가
        unit_power_mw_mp: 0.9
        ppc: 8.0
        idc: 0.0
        vdd: VDD_CAM
        dvfs_group: CAM
        substitutes: [Normal]             # 선택: 화질 평가가 필요한 절감 후보로 조합 탐색에 포함
        iq_eval: required
        label: MCSC low power
```

| mode의 용도 | 방법 |
|---|---|
| 정식: 특정 variant가 항상 그 mode로 동작 | `variants.yaml`의 해당 variant에 `node_configs.<node>.selected_mode: LowPower` |
| 후보: 절감 예측만 (IQ 평가 전) | 위의 `substitutes: [Normal]`. 조합 탐색 → 예측 현황의 "절감 option"에 나온다. variant는 만들지 않는다 |

### 2.3 DMA port

DMA port 정보는 두 곳에 있고, **port 이름을 같게** 유지해야 한다.

| 위치 | 용도 |
|---|---|
| IP 파일 `capabilities.properties.modules[]` (`name`, `type`, `direction`, `supported_compressions`) | Pipeline 상세, write 검증, 탐색의 port별 compression 지원 판정 |
| `scenario.yaml` `pipeline.edges[].port_pairs`, `pipeline.buffers`, variant `topology_patch.add_edges` | **simulation의 DMA 전송량** |

```yaml
# IP 파일: port 추가 / 수정 / 삭제는 list 항목을 직접 편집한다
    modules:
    - name: MCSC_WDMA_W1
      type: DMA
      direction: write
      supported_compressions: [COMP_OFF, COMP_YUV_LOSSLESS]    # lossy 삭제
    - name: MCSC_WDMA_W5                                       # 추가
      type: DMA
      direction: write
      supported_compressions: [COMP_OFF]
```

```yaml
# scenario.yaml: 연결 port 변경
  edges:
  - from: mcsc
    to: gdc_o
    type: M2M
    buffer: MCSC_VIDEO
    port_pairs:
    - {src: MCSC_WDMA_W5, dst: GDC_RDMA}                       # W1 → W5
```

- variant의 `topology_patch.add_edges`에도 같은 port가 나오면 함께 바꾼다.
- 찾기: `grep -n MCSC_WDMA_W1 authoring/projects/sm-s957b/scenarios/*/*.yaml`

### 2.4 Compression 지원 / 기본값 / ratio

| 항목 | 위치 | 탐색 영향 |
|---|---|---|
| IP 수준 지원 | IP `supported_features.compression` | endpoint IP 중 하나라도 지원하지 않으면 그 buffer는 제외 |
| DMA port 수준 지원 | IP `properties.modules[].supported_compressions` | 영향받는 port 중 하나라도 지원하지 않으면 그 mode는 제외 (`DMA port without COMP_YUV_LOSSY: mfc_enc.MFC_RDMA`) |
| 기본 압축 (정식 구성) | `scenario.yaml` `pipeline.buffers.<BUF>.compression` | 이미 압축된 buffer는 탐색 대상에서 빠진다 |
| ratio | `soc-exynos2700.yaml` `compression_modes.<MODE>.comp_ratio` | 탐색과 simulation의 BW 감소량 |

### 2.5 새 IP / IP 교체 / 삭제

1. `docs/00_hw/ip-<new>-s5e9975.yaml`을 추가한다. 비슷한 IP 파일을 복사한 뒤 `id`와 값을 고친다.
2. `soc-exynos2700.yaml`의 `ips:`에 `{ref: ip-<new>-s5e9975, instance_count: 1}`을 추가한다.
3. `scenario.yaml`의 `pipeline.nodes`에서 해당 node의 `ip_ref`를 새 IP로 바꾼다.
4. 쓰지 않는 IP는 파일을 지우고, `ips:`와 node 참조도 함께 지운다. 남은 참조가 있으면 compile이 알려 준다.

### 2.6 DVFS table

`docs/00_hw/dvfs-exynos2700-<rev>.yaml`로 추가한다 (`kind: soc.dvfs_table`, `soc_ref: soc-exynos2700`).
현재 `dvfs-exynos2700-sample-v0`은 SAMPLE이며, report와 UI에 SAMPLE로 표시된다.

---

## 3. Scenario 수정

### 3.1 variants.yaml 구조

`variants.yaml`은 **compact** 형식이다.
- `extends:`가 없는 항목은 완전한 variant다.
- `extends: <부모>`가 있는 항목은 부모 위에 덮는 patch다. `$unset: [key]`는 부모 key를 지운다.
- 따라서 **부모 항목을 고치면 자식 variant도 바뀐다.** 수정 전에 영향 범위를 확인한다.

```bash
uv run python -m scenario_db.authoring show sm-s957b uc-cam-recording-e2700 cam-rec-r1-uhd30-vdis
# # extends: cam-rec-r1-fhd30-vdis
# # editing its entry also changes: cam-rec-r1-uhd60-psm, cam-rec-r1-uhd120, ...
# (완전히 풀린 variant 내용)
```

- 한 variant만 바꾸려면 **그 variant 항목**에 값을 추가한다. 자식이 없으면 영향은 그 variant뿐이다.
- 여러 variant에 공통이면 공통 부모 항목을 고친다.

### 3.2 EIS를 default로 켜기

EIS가 꺼진 variant에는 다음 세 가지가 들어 있다.
- `routing_switch.disabled_nodes`에 `eis`, `gdc_m`, `gdc_o`
- MCSC→DPU/MFC 우회 edge (`topology_patch.add_edges`)
- `stabilization` 없음

예: `cam-rec-r1-uhd60-psm` 항목을 아래처럼 고친다.

```yaml
- id: cam-rec-r1-uhd60-psm
  extends: cam-rec-r1-uhd30-vdis        # 부모(uhd30-vdis)는 EIS on
  design_conditions:
    $unset:                             # stabilization, is_scenario를 목록에서 뺀다 (부모 값을 유지)
    - priority_recording
    - ...
    subscenario: UHD_60FPS_VIDEO
    ...
  routing_switch:
    disabled_nodes:                     # eis, gdc_m, gdc_o 삭제
    - sensor_rear2
    - sensor_rear3
    - sensor_front
    - vps_dof
    - vps_seg
  topology_patch:                       # mcsc→dpu, mcsc→mfc_enc 우회 edge 삭제
    ...
```

- 확인: `show`로 결과를 본다. `routing_switch`에 eis가 없고, `stabilization: SWVDIS`여야 한다.
- 이 variant를 부모로 쓰는 자식(`cam-rec-r1-8k30-psm`, `cam-rec-r1-uhd60-pro`)도 함께 바뀐다. 자식은 원래대로 두려면 자식 항목에 기존 값을 적는다.
- EIS를 켜면 knob의 param rule(`eis_margin_pct 15`)과 bcrop power option이 자동으로 적용된다.
- `eis` SW timing은 `sw_timing.yaml`의 `eis-a` group에 있다. 2700 실측값은 `sw_timing.measured.yaml`에 넣는다.
- 참고 수치: UHD60 PSM에서 EIS를 켜면 995 → 1352 mW (sample DVFS).

### 3.3 Size 변경

variant마다 `size_overrides`에 anchor 값(`sensor_full`, `record_out`, `mlsc_out`, `pyramid_l0~l4`, …)이 있고, 이 값이 scenario의 `size_profile.anchors`보다 우선한다.

```yaml
# variants.yaml: 해당 variant(또는 부모) 항목의 size_overrides
  size_overrides:
    sensor_full: 4000x2252
    mlsc_out: 4000x2252
    pyramid_l0: 4000x2252
    pyramid_l1: 2000x1126
    pyramid_l2: 1000x563
    pyramid_l3: 500x282
    pyramid_l4: 250x141
```

의존 anchor를 직접 계산하기 싫으면 `sizes.yaml`의 `derived`에 규칙을 두고 `force: true`로 다시 계산시킨다.

```yaml
# sizes.yaml
derived:
  mlsc_out:   {from: sensor_full, force: true}
  pyramid_l0: {from: mlsc_out, force: true}
  pyramid_l1: {from: pyramid_l0, scale: 0.5, round: ceil, force: true}
  pyramid_l2: {from: pyramid_l1, scale: 0.5, round: ceil, force: true}
  pyramid_l3: {from: pyramid_l2, scale: 0.5, round: ceil, force: true}
  pyramid_l4: {from: pyramid_l3, scale: 0.5, round: ceil, force: true}
```

- `sizes.yaml`의 `bindings`에 연결된 node는 anchor 값을 따라 `sim.width/height`가 자동으로 바뀐다.
  - sensor_full: byrp~mcsc
  - record_out: gdc_o, mfc_enc
  - preview_out: dpu
- 녹화 해상도를 바꿀 때는 `size_overrides.record_out`을 고친다.
- node 하나만 다르게 하려면 `node_configs.<node>.sim: {width, height}`를 준다. 이 값이 binding보다 우선한다.
- bcrop 같은 knob의 anchor는 derived 규칙 다음에 계산되어 그 위에 덮인다.

### 3.4 variant 추가 / 제거

```yaml
- id: cam-rec-r1-uhd30-log              # 추가: 가까운 variant를 부모로
  extends: cam-rec-r1-uhd30-vdis
  design_conditions: {camera_mode: log_video, hdr: LOG}
```

- 제거: 항목을 지운다. 그 항목을 부모로 쓰던 자식이 있으면 compile이 오류를 낸다. 자식의 `extends`를 다른 variant로 바꾸거나, 자식에 필요한 값을 옮겨 적는다.
- 이미 DB에 적재된 variant를 지울 때는 `authoring/retired.yaml`에도 추가한다.
- IQ 평가가 필요한 절감안(bcrop, L0 skip, low-power mode)은 variant로 만들지 않는다. `knobs.yaml`의 `explore` 또는 IP mode의 `substitutes`로 선언한다.

---

## 4. Scenario 추가

| 방법 | 절차 |
|---|---|
| 기존 2700 scenario 복제 | `cp -r authoring/projects/sm-s957b/scenarios/uc-cam-recording-e2700 authoring/projects/sm-s957b/scenarios/uc-cam-recording-night-e2700` → 새 폴더의 `scenario.yaml`에서 `id`, `metadata.name`, `metadata.canonical_usecase`(과제 간 비교 키, 예: `uc-cam-recording-night`)를 바꾼다. `sw_timing.measured.yaml`의 `scenario:`도 새 id로 바꾸고, `variants.yaml`을 편집한다 |
| 2600의 다른 scenario 가져오기 (예: preview) | 1) `authoring/projects/sm-s947b/scenarios/uc-cam-preview-e2600`을 `.../sm-s957b/scenarios/uc-cam-preview-e2700`으로 복사한다. 2) 파일 안의 id를 바꾼다: `sed -i 's/-e2600/-e2700/g; s/s5e9965/s5e9975/g; s/proj-sm-s947b/proj-sm-s957b/g' <폴더>/*.yaml`. 3) sensor / SW profile 참조가 있으면 2700 id(`...-s5e9975`)인지 확인한다. 4) `retired.yaml`에서 해당 id를 **먼저** 뺀다 |
| 완전히 새 scenario | 위 폴더 구조(`scenario.yaml` + `variants.yaml` + `sizes.yaml` + `sw_timing.yaml`)를 새로 만든다 |

- compile이 참조 오류(없는 IP, node)를 알려 준다.
- id 규칙은 `uc-<domain>-<use case>-e2700`이다.

---

## 5. Sensor 정보

| 대상 | 파일 (`authoring/platforms/exynos2700/docs/`) | 수정 위치 |
|---|---|---|
| sensor timing (line length, frame length, pixel clock) | `00_sensor/timing-s5kgng.yaml` (`id: sensortiming-s5kgng-seta-19p2-s5e9975`) | `modes.<mode>`, `revision` |
| sim용 sensor mode (크기, fps, MIPI, lane) | `00_hw/ip-sensor-gng-s5e9975.yaml` | `capabilities.properties.modes.<mode>`, `operating_modes` |
| module / CSIS wiring / mode→timing 연결 | `00_sensor/m2s/sensor-gng.yaml` (`id: sensor-gng-m2s-s5e9975`) | `module_properties`, `csis_wiring`, `modes.<mode>.timing_binding` |
| board별 sensor 배치 | `00_sensor/board-lineup-s5e9975.yaml` | `boards.<board>.configs[].lineup` |
| variant가 쓰는 sensor mode | `variants.yaml` | `node_configs.sensor_rear.selected_mode`, `design_conditions.sensor_input_fps` |

```yaml
# 00_sensor/timing-s5kgng.yaml
revision: 2700-evt0-20261001
modes:
  cis_4sum_ln4_raw10_4080x2296_30fps_3993msps:
    line_length_pck: 15000
    source: {basis: 2700 EVT0 setfile, path: is-cis-gng-2700.h}
```

**다른 sensor로 교체하는 순서**
1. `00_hw/ip-sensor-<name>-s5e9975.yaml`과 `00_sensor/` catalog·timing 파일을 추가한다.
2. `scenario.yaml`에서 `sensor_rear` node의 `ip_ref`를 바꾼다.
3. variant의 `selected_mode`와 size(§3.3)를 맞춘다.
4. `board-lineup-s5e9975.yaml`의 lineup을 갱신한다.

---

## 6. 실측

`db_Exynos2700_SM-S957B/measurements/<variant>/meta.yaml` + `rail_power_by_run.csv`에 있다 (현재 DUMMY).
- 수정할 때마다 `provenance.revision`을 +1 한다.
- 실측으로 바꿀 때는 `collection_method`와 `device_id`를 실제 값으로 적는다.
- 형식은 [Measurement Import Guide](../measurement/measurement-import-guide-ko.md)를 따른다.

---

## 7. 2600 변경 확인 (parent-diff)

```bash
uv run python -m scenario_db.authoring parent-diff sm-s957b
```

```json
{
  "changed": [
    {"doc": "ip-mcsc-is-v15-s5e9975", "parent": "ip-mcsc-is-v15-s5e9965",
     "diff": ["~ capabilities.sim.modes.Normal.unit_power_mw_mp"]},
    {"doc": "uc-cam-recording-e2700", "parent": "uc-cam-recording-e2600",
     "variants_changed": ["cam-rec-r1-uhd30-vdis"],
     "in_project": {"cam-rec-r1-uhd30-vdis": ["~ design_conditions.record_bitrate_mbps"]}}
  ],
  "new_in_parent": [], "removed_in_parent": []
}
```

| 항목 | 의미 |
|---|---|
| `changed` | eject 이후 2600에서 바뀐 문서/variant, 그리고 지금 2600(2700 id로 변환)과 2700 사이에 다른 경로 |
| `diff` / `in_project` | 목록에는 2700에서 의도적으로 바꾼 값도 함께 나온다. 2600 변경이 2700에도 필요한지 판단해서 해당 파일에 직접 반영한다 |
| `new_in_parent` | eject 이후 2600에 새로 생긴 문서 |
| `removed_in_parent` | eject 이후 2600에서 사라진 문서 |

검토와 반영이 끝나면 기준점을 현재 2600으로 옮긴다. 같은 변경이 다음 `parent-diff`에 다시 나오지 않는다.

```bash
uv run python -m scenario_db.authoring parent-diff sm-s957b --accept
```

---

## 8. 자주 하는 실수

| 증상 | 원인 | 해결 |
|---|---|---|
| 수정이 dev_up 후 사라짐 | `db_Exynos2700_SM-S957B/00~02`를 직접 수정 | `authoring/`에서 수정 |
| 다른 variant까지 바뀜 | `extends` 부모 항목을 수정 | `show`로 영향 범위 확인 후 대상 variant 항목에 수정 |
| size를 바꿨는데 그대로 | variant의 `size_overrides`가 우선 | `size_overrides` 수정, 또는 `sizes.derived … force: true` |
| 예측 / timing diagram이 예전 값 | simulation evidence 미재생성 | §1-2), 조합 탐색 재실행 |
| 다시 가져온 scenario가 매번 초기화됨 | `retired.yaml`에 남아 있음 | retired 목록에서 삭제 |
| 탐색에서 "DMA port without …" | port가 해당 mode 미지원 | IP `modules`에 지원 추가, 또는 lossless 탐색 |
| 2600의 수정이 2700에 없음 | eject 이후에는 자동 전파되지 않음 | `parent-diff`로 확인해서 반영 |

---

## 부록. 상속형 파생 과제 (patch / overlay)

eject하지 않은 파생 과제(예: 새 SoC 검토용)는 여전히 상속 방식으로 만든다.

**patch 문법** (`platforms/<p>/patches/<doc id>.yaml`, overlay):

| 형태 | 동작 |
|---|---|
| `key: value` | dict는 merge, list는 통째로 교체 |
| `$unset: [k]` | key 삭제 |
| `$append: {key: [items]}` | list에 항목 추가 |
| `$remove: {key: [items / {selector}]}` | list에서 항목 제거 |
| `$items: {key: {by: name, patch: {...}, remove: [...], add: [...]}}` | list의 한 항목만 수정 |

**overlay** (`projects/<p>/scenarios/<parent uc>/overlay.yaml`):

| key | 용도 |
|---|---|
| `scenario_patch` | scenario 본문 patch |
| `pipeline` | node/edge/buffer 추가·삭제·교체, `rename_ports` |
| `variants.keep` / `add` / `patch` | variant 선택·추가·수정 |
| `variants.patch_resolved` | 선택자로 여러 variant 일괄 patch |
| `sizes` / `sw_timing` / `knobs` | 해당 파일 patch |

**scenario 복제**: `scenarios/<new id>/overlay.yaml`에 `from: <parent uc>`를 둔다.

- 예제와 동작 검증: `tests/unit/authoring/test_authoring_2700_cases.py`. eject 전 2700 정의가 `tests/unit/authoring/fixtures/inherited_2700`에 보존되어 있다.
- 상속형 과제를 파일 편집형으로 바꾸려면 `uv run python -m scenario_db.authoring eject <project>`를 실행한다.
  - patch와 overlay가 파일에 반영된 뒤 삭제된다.
  - compile 결과가 eject 전과 같지 않으면 아무것도 쓰지 않는다.
