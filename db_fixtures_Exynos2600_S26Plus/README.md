# IS v15 Camera Recording fixture

S26Plus(m2s)의 wide sensor는 GNG를 사용한다. HP2는 다른 모듈 구성의 대안으로 보존한다. `00_hw/ip-sensor-*.yaml`의 DTS/CIS 출처와 `source_sha256` 등의 provenance를 통해 커널 확인값과 fixture 가정을 구분한다. 기존 다른 usecase의 공용 ISP 정의는 유지한다.

## 구조와 DMA

RT는 Sensor → CSIS → PDP → BYRP → RGBP → YUVSC → MLSC이며 sensor v-valid에 동기화한다. NRT는 MTNR → MSNR → YUVP → MCSC이다. 두 경로 내부는 OTF이고, MLSC → MTNR은 pyramid 메모리를 통한 M2M이다. KPI recording에서 YUVSC downscale은 꺼져 있다.

MLSC L0–L4와 MTNR current/history의 커널 포트를 개별 선언했다. L0는 Y, L1–L4는 Y/U/V의 3개 DMA plane으로 모델링한다. 이전 프레임은 `pipeline.buffers.TNR_PREV_L*.history`로 선언해 DAG self-cycle 없이 read/write 트래픽을 계산한다. 같은 MCSC 출력의 여러 소비자는 write를 중복 계산하지 않는다. FHD preview/video는 W0를 공유하고 다른 해상도는 W0/W1을 사용한다. MCSC 카탈로그에는 W0–W4를 보존한다.

LME와 VPS OD를 별도 M2M 노드로 구성하고 DOF/SEG는 기본 비활성화한다. MCSC 이후 EIS CPU 작업 하나의 결과로 preview/video GDC instance 0/1을 동작시킨다. EIS가 없는 variant는 MCSC 출력에 직접 연결한다.

## 교체할 SW 가정값

단위는 ms이며 **실측 데이터가 아니다**. `02_definition/uc-camera-recording.yaml`의 variant `node_configs.<node>.sw_timing`에서 수정한다.

| Node | min | mean | max | 비고 |
| --- | ---: | ---: | ---: | --- |
| post_crta | 0.1 | 0.3 | 0.5 | RT 종료 후 평균 시작 지연 1.0 |
| pre_me_rta | 2.5 | 3.0 | 4.0 | LME HW 시간 포함 |
| post_irta | 3.0 | 4.0 | 5.6 | MV 후처리/TNR 강도 결정 |
| eis | 2.5 | 3.0 | 6.0 | 한 SW 작업이 preview/video GDC를 제어 |

`design_conditions.sw_timing_case`로 min/mean/max를 선택한다. `start_jitter_mean_ms`는 측정 분포가 없어 모든 case에서 일정한 1 ms release delay로 사용하며 CPU 실행시간에 더하지 않는다. 순수 CPU 작업은 하나의 CPU resource를 공유한다. `pre_me_rta.includes_hw_nodes: [lme]` 때문에 LME 실행시간을 aggregate 뒤에 다시 더하지 않는다. CPU/HW 시간 분리가 없으므로 aggregate 전체를 CPU 전력으로 계산하지 않는다.

사내 측정값을 넣을 때 각 수치, `value_source: measured`, `source_note`를 함께 갱신한다. 실측 evidence에는 scenario/variant/project와 SW baseline, timestamp 등 실행 조건도 맞춰 넣는다. 기존 measurement fixture는 과거 자료이며 새 v15 모델을 보정한 측정값으로 간주하지 않는다. SW 통계는 DB 저장, 조회, 비교 및 Evidence/Timeline UI까지 보존된다. min/max로 p95를 만들지 않는다.

## 재현과 결과

저장소 `implementation/`에서 실행한다.

```powershell
.\.venv\Scripts\python.exe scripts/verify_is_v15_camera.py --write-evidence
.\.venv\Scripts\python.exe -m scenario_db.etl.loader db_fixtures_Exynos2600_S26Plus --strict --report-json output/is-v15-camera/etl-report.json
.\.venv\Scripts\python.exe -m pytest tests/integration/test_is_v15_camera.py -q
```

검증기는 모든 effective variant의 DAG와 DMA 선언을 확인하고, FHD/UHD 30/60fps 네 KPI에 SW min/mean/max 및 300/400/600/800/1000 MHz 후보를 조합한다. 후보 주파수는 실제 DVFS table이 아닌 가정값이다. 공유 domain 적용 후 8프레임 출력 cadence와 기본 3프레임 latency budget을 검사해 통과한 가장 낮은 후보를 선택한다. `output/is-v15-camera/verification.json`과 `.md`에 탈락 후보도 남는다.

RAW10 sensor mode와 단일 EIS로 탐색 결과를 다시 생성했다. 기본 3프레임 latency 조건에서 FHD/UHD 30fps는 min/mean/max 모두 300 MHz 후보, 60fps는 min 600 MHz 및 mean 1000 MHz 후보가 통과했다. 이는 요청 클록 후보이며 센서 입력·공유 도메인 하한이 적용된 실제 설정 클록은 evidence의 DVFS breakdown을 참조한다. 최대 SW 시간의 60fps는 통과 후보가 없다. 생성 결과는 실측·전력 최적점이 아닌 estimated/exploration_only이다.

`import_bundle.json`은 Write API가 지원하는 48개 canonical 정의만 포함한다. simulation profile과 evidence까지 로드하려면 strict ETL을 사용한다. YAML 정의 변경 시 bundle/report도 같이 갱신한다.

## 아직 필요한 실제 정보

- IP clock/voltage/DVFS table과 power coefficient: 기존 모델 차용 또는 capacity 가정이다. MLSC/GDC/VPS의 미확인 core power는 합계에서 제외되므로 전력 최적점으로 해석하지 않는다.
- PDP/BYRP 통계와 MV 결과, L0 chroma 보조 입력, MTNR weight/SEG의 활성 여부·크기·format: 포트 카탈로그에 있는 항목이라도 크기가 없는 DMA는 BW에 임의 추가하지 않는다.
- LME 입력 1008×756, FDPIG RGB 512×288, CAV RGB 320×180, preview FHD, compression 및 pyramid layout은 교체 가능한 가정이다.
- 전 프레임 history는 warm-start steady-state를 가정한다. startup 초기화와 frame-to-frame buffer hazard의 상세 스케줄은 포함하지 않는다.
- VPS DOF/SEG를 켜려면 실제 입력 DMA와 timing을 함께 정의하고 LME를 포함한 preME aggregate 가정도 수정해야 한다.


## RAW10 및 보조 DMA 수정

모델명은 SM-S947B를 유지한다. 아래 센서 입력은 사용자 확인값이다.

| Recording scenario | Sensor size | Sensor fps | Format |
| --- | --- | ---: | --- |
| FHD30 / UHD30 | 4080×2296 | 30 | RAW10 |
| FHD60 / UHD60 | 4080×2296 | 60 | RAW10 |
| UHD120 | 4080×2296 | 120 | RAW10 |
| FHD120 / FHD240 | 2040×1148 | 120 | RAW10 |

FHD120/240의 120fps 설정은 확인된 CIS 240fps 모드에서 line timing을 차용한 사용자 지정 mode다. frame length를 두 배로 둔 것은 임시 가정이며 실제 register 설정으로 확정한 값이 아니다. FHD240의 시나리오 이름/출력 목표 240fps와 센서 입력 120fps는 별도로 보존한다. 출력 cadence 구현은 추가 확인이 필요하다.

L0는 MLSC output size이며 L1–L4는 직전 layer의 가로·세로를 각각 1/2(올림)로 줄인다. 현재 recording은 YUVSC downscale이 꺼져 있어 MLSC output과 sensor size가 같다.

- BYRP: `IS_LVN_BYRP0_BYR`를 `BYRP_WDMA_BYR`에 매핑. `byrp.video_snapshot_enabled`가 켜질 때 `BYRP_BAYER_DUMP` full-size RAW10 WDMA를 계산한다.
- RGBP: DRC/HIST/SAT LVN 선언을 보존한다. HIST는 커널 subdev의 논리 LVN이며 physical DMA API 매핑은 미확인이다. 크기가 없는 세 출력은 BW에서 제외한다.
- MLSC: LMEDS는 motion estimation용 Y, FDPIG는 OD용 RGB 512×288, CAV는 RGB 320×180, SVHIST는 histogram이다. RGB bitdepth 8은 가정이다. CAV는 크기만 정의된 선택 출력이며 기본 비활성화한다.
- YUVP: DRC0/DRC1 RDMA와 사용자 확인 SVHIST 논리 RDMA를 연결한다. SVHIST의 실제 kernel DMA/LVN 매핑은 미확인으로 표시한다. 통계 크기가 미확인인 버퍼는 `size_status: unknown`이며 화면에도 sensor/record 크기로 대체 표시하지 않는다.

사내 값 입력 시 버퍼의 size_ref/format/bitdepth를 정의하고 size_status를 갱신한다. downstream consumer가 모델링되지 않은 보조 출력은 `pipeline.buffers.<id>.dma`에 node_id/write_ports/activation_flag 또는 enabled로 선언한다. CAV는 buffer_overrides에서 dma.enabled를 설정해 활성화할 수 있다.
