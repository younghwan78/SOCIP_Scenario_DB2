# 00_sensor — S5E9965 보드 카메라 센서 카탈로그 (DT 원문 기준)

S5E9965 트리에 있는 **3개 보드 × 20개 센서 모듈 × 449개 모드**를 device tree 정의 그대로 정리한 것이다.
`tools/build_sensor_catalog.py`가 DT를 빌드 시점에 파싱해 생성한다. 숫자는 손으로 옮기지 않는다.

```
00_sensor/
  board-lineup-s5e9965.yaml   보드 7개 구성 × 포지션별 센서, CSIS 채널 배선, 모듈-구성 사용 관계
  erd9965/   sensor-{3j1,hp2,imx564,imx754,imx854}.yaml
  m1s/       sensor-{3k1,3ld,3lu,gn3,gng,imx564-ff,imx874,imx955,jn3}.yaml
  m2s/       sensor-{3ld,gng,hp2,imx564-ff,imx874,jn3}.yaml
```

## 00_hw/ip-sensor-*.yaml 과의 관계

| | `00_hw/ip-sensor-*.yaml` | `00_sensor/` (이 폴더) |
| --- | --- | --- |
| 용도 | 시뮬레이터 입력 (m2s 한정) | DT 원문 아카이브, 보드 비교, exploration 입력 |
| 보드 | m2s만 | erd9965 / m1s / m2s |
| 모드 | bare `modeN`만 (87개) | **전부 (449개)** — `_aeb`, `_nfi`, `_ai_remosaic`, `_dcg`, `_ln`, `_phy_tune` 포함 |
| VC 채널 | 없음 | VC별 map/format/데이터종류/크기 |
| CSIS 배선 | 없음 | `csi_ch`, `use_cphy`, `scramble` |

**두 폴더는 서로 덮어쓰지 않는다.** `00_hw` 쪽은 `build_camera_fixture.py`가, 이 폴더는
`build_sensor_catalog.py`가 소유한다.

## 보드별 라인업

| 보드 | 구성 | Wide(0) | Front(1) | Tele(2) | UW(4) | Tele2(6) |
| --- | --- | --- | --- | --- | --- | --- |
| **erd9965** | `s5e9965-erd9965-camera` | S5KHP2 | S5K3J1 | IMX754 | IMX564 | IMX854 |
| **m1s** | `m1s_camera` | **S5KGN3** | IMX874 | S5K3K1 | IMX564 | – |
| | `m1s_camera_00` | **S5KGN3** | S5K3LU | S5K3K1 | IMX564 | – |
| | `m1s_camera_09` | **S5KGNG** | IMX874 | S5K3LD | S5KJN3 | – |
| | `m1s_camera_17` | **S5KGNG** | IMX874 | S5K3LD | IMX564 | – |
| **m2s** | `m2s_camera` | **S5KGNG** | IMX874 | S5K3LD | IMX564 | – |
| | `m2s_camera_02` | **S5KHP2** | IMX874 | – | S5KJN3 | – |

> **GNG / GN3 / JN3 혼동 주의.** 이름이 비슷하지만 전부 다른 센서다.
> `SENSOR_NAME_S5KGN3 = 71`(m1s Wide), `S5KHP2 = 74`(erd·m2s Wide),
> `S5KGNG = 82`(m1s·m2s Wide), `S5KJN3 = 83`(UW).
> **GN3는 m1s 전용이고 m2s(SM-S947B)에는 없다.** m2s Wide는 GNG 또는 HP2다.

## 센서별 모드 수

| 센서 | 포지션 | erd9965 | m1s | m2s | 최대 MIPI 링크 |
| --- | --- | ---: | ---: | ---: | ---: |
| S5KHP2 | Wide | 38 | – | **45** | 25,453 Mbps |
| S5KGNG | Wide | – | 30 | **30** | 27,380 Mbps |
| S5KGN3 | Wide | – | 40 | – | 22,731 Mbps |
| IMX955 | Wide | – | 14 (orphan) | – | 26,564 Mbps |
| IMX874 | Front | – | 28 | 28 | 12,124 Mbps |
| S5K3LU | Front | – | 18 | – | 10,344 Mbps |
| S5K3J1 | Front | 12 | – | – | 9,572 Mbps |
| S5K3LD | Tele | – | 17 | 17 | 12,336 Mbps |
| S5K3K1 | Tele | – | 11 | – | 9,212 Mbps |
| IMX754 | Tele | 9 | – | – | 13,035 Mbps |
| IMX854 | Tele2 | 1 | – | – | 19,097 Mbps |
| IMX564 | UW | 9 | 21 | 21 | 23,170 Mbps |
| S5KJN3 | UW | – | 30 | 30 | 23,780 Mbps |

**같은 센서라도 보드마다 모드 수가 다르다** (HP2: erd 38 vs m2s 45). 모듈 DT가 보드별로
따로 있기 때문이다. 그래서 카탈로그 키는 (보드, 센서)다.

## 모드 레코드 구조

각 모드는 세 층으로 기록한다.

```yaml
mode2_aeb_nfi:
  dt:                          # DT 원문 그대로 + 줄 번호
    common: [4000, 3000, 60, 0, 2, CSI_DATA_LANES_3, 3712, CSI_MODE_VC_DT, LRTE_DISABLE, PD_MOD3, EX_AEB]
    source_line: 134
    dma_node_count: 2          # dma0/dma1 자식을 쓰는 경우에만
  decoded:                     # enum 해석
    size: [4000, 3000]
    fps: 60
    lanes: 3                   # CSI_DATA_LANES_3 == 2, 드라이버가 +1 (is-hw-dvfs.c)
    mipi_speed_mbps: 3712
    pd_mode: PD_MOD3           # + pd_mode_value: 3
    ex_mode: EX_AEB            # + ex_mode_value: 8
  vc:                          # VC별 채널 (CSIS 입력 BW의 근거)
    dma0:
      vc0: {map: 0, size: [4000,3000], hwformat: HW_FORMAT_RAW10, bits_per_pixel: 10, data_class: image}
      vc2: {map: 1, size: [4000,376],  hwformat: HW_FORMAT_RAW10_POTF, format_flags: [POTF], data_class: pd_horizontal}
    dma1: {...}
  option: {votf: 0, max_fps: 60, img_vc: [0,6], ex_mode_extra: EX_EXTRA_NFI}
  derived:                     # DT에서 산술적으로 따라오는 값
    mipi_link_mbps: 25453
    phy: CPHY
    csis_input_mbps: 9357.5
    link_utilization_pct: 36.8
```

### 파싱 근거

| 항목 | 커널 근거 |
| --- | --- |
| `common` 필드 순서 | `is-dt.c: is_cis_modes_parse_dt()` — width, height, framerate, settle, mode, lanes, mipi_speed, interleave, lrte, pd_mode, ex_mode |
| `vcN` 필드 순서 | `is-dt.c: is_cis_modes_dma_parse_dt()` — map, hwformat, data, width, height |
| 레인 수 | `is-hw-dvfs.c: lanes = cfg->lanes + 1` (`CSI_DATA_LANES_3` == 2 → 3레인) |
| **MIPI 링크 레이트** | `is-hw-dvfs.c: get_mbps() = mipi_speed * lanes * 16 / (cphy ? 7 : 16)` |
| enum 값 | `dt-bindings/camera/exynos_is_dt.h` — 하드코딩 없이 파싱 |

`common`이 10칸인 모드(91개)는 `ex_mode` 칸이 없다. 드라이버가 `cfg->ex_mode`를 0으로 두므로
`EX_NONE`으로 채우고 `ex_mode_source`에 그 사실을 적는다.

## 생성 과정에서 드러난 것

1. **C-PHY가 링크 계산을 좌우한다.** `use_cphy`는 모듈 DT가 아니라 **보드 config의 `is_sensorN`
   노드**에 있다. C-PHY는 심볼당 16/7 비트라 링크 레이트가 D-PHY 대비 2.29배다.
   Wide 센서는 전부 C-PHY, Front/Tele 일부는 D-PHY다.

2. **다중 노출 모드의 VC 합산은 과다계상이다 (29개 모드).** `_aeb` / `_dcg` 모드는 이미지 VC를
   2개 선언하는데 노출이 시분할되므로, DT 프레임레이트로 두 VC를 모두 더하면 링크 용량을
   초과한다(최대 167%). `csis_input_mbps_per_exposure`를 함께 넣고 `link_overcommit`에 이유를
   적었다. **실제 AEB 프레임레이트 확인이 필요하다.**

3. **원인 미확인 오버커밋 1건** — `erd9965/sensor-hp2.yaml: mode13` (8000×4500 @30fps, 110.4%).
   이미지 VC가 1개라 다중 노출로 설명되지 않는다.

4. **`EX_MPC`는 정의되지 않은 토큰이다.** `erd/camera/module_hp2.dtsi:358`에서 쓰는데
   어느 헤더에도 `#define`이 없다. 이 모드가 실제로 빌드되는지 확인이 필요하다.

5. **`module_imx955.dtsi`는 orphan이다.** m1s에 모듈 DT는 있으나 4개 보드 구성 중 어느 것도
   include하지 않는다.

6. **ERD는 id 1을 두 노드가 공유한다** — `is_sensor1`(okay)과 `is_sensor5`(disabled).
   enabled 쪽을 쓰고 `also_declared_by`에 나머지를 남겼다.

## 재생성

```bash
cd scenario_collector
python3 tools/build_sensor_catalog.py
```

idempotent하다. 커널 드롭이 바뀌면 재실행으로 따라간다. 각 파일의 `provenance`에
모듈 DT와 bindings 헤더의 sha256이 들어 있다.
