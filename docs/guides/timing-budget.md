# Stage Timing Budget (SW margin 예측)

기존 rule of thumb(frame의 25%를 SW margin으로 두고 HW가 75% 안에 끝나도록 clock을 설정) 대신,
이전 과제의 SW runtime/latency와 차기 과제의 SW 증가를 반영해 **stage별 HW 예산 → IP clock → DVFS level → Power/BW**를 산출한다.

- 엔진: `src/scenario_db/sim/timing_budget.py`
- API: `POST /api/v1/timing-budget/variant`, `POST /api/v1/timing-budget/fleet` (analyst 이상)
- UI: `#/timing` (Variant 상세), `#/timing-fleet` (전체 scenario)
- CLI: `scripts/timing_budget_report.py`

## 1. Stage slot 모델

stage 사이는 memory(M2M)이므로 pipeline으로 동작한다. 각 stage가 1 frame period `P = 1000/fps` 안에 끝나면 된다.

| Stage | 구성 | HW 예산 |
| --- | --- | --- |
| RT | sensor 동기 OTF (CSIS~YUVSC 등) | `P × (1 − rt_margin)`, 기본 25% rule |
| NRT | gating SW + MTNR~MCSC (M2M) | `P − critical SW(runtime+latency) − IP overhead` |
| Post-NRT | memory → EIS(SW) → GDC | `P − EIS 등 post SW − overhead` (1 frame latency 가정) |
| Output | DPU(preview), MFC/APV(video), writer SW | `P × (1 − output_margin)`, 기본 25% rule |

- critical SW = SW DAG의 **최장 직렬 경로**. PIP/dual의 병렬 chain은 합산하지 않는다.
- SW 분류: output 하류 → output, NRT HW 조상 → nrt, NRT HW 하류 또는 GDC 입력 → post.
- EIS: `auto`면 variant의 stabilization이 있을 때 ON. post SW 중 이름에 `eis`가 있거나 GDC로 들어가는 task.

## 2. Clock / DVFS

- node margin `m = 1 − budget / (P·(1+h_blank))`, `required = pixels·fps / (1−m) / ppc`.
- 여러 stream이 같은 IP를 공유하면 `m_k = 1 − (1−m)/k`.
- **MFC dual core**: UHD 이상이면(`mfc_dual=auto`) MFC/MFD가 절반씩 병렬 처리한다. 폭 ½ → clock ½, frame 시간은 같고 power는 × cores.
- DVFS: required 이상인 최소 level을 쓰고 DVFS domain 정렬을 반영한다. power는 `(V/710 mV)²`로 scale.
- 기본 DVFS는 해당 SoC의 최신 `SocDvfsTable`이다. 요청의 `dvfs_tables`/`dvfs_table_ref`로 override할 수 있다.

## 3. 판정

- **간격(합격 기준)**: timeline simulation에서 DPU(preview)와 MFC/APV(video)의 frame 완료 간격이 `P ± interval_tolerance·P`(기본 ±0.1%) 안이어야 한다.
- latency는 참고값으로만 보고한다(판정에 쓰지 않음).
- verdict:
  - `ok`: rule clock 그대로 가능
  - `clock_up`: SW 반영 시 clock 상향 필요
  - `fail`: 예산이 0 이하, DVFS max 초과, 또는 간격 이탈

## 4. 입력 옵션 (`options`)

| 필드 | 기본 | 설명 |
| --- | --- | --- |
| `statistic` | `max` | SW runtime/latency 통계 (`max`/`mean`/`min`) |
| `eis` | `auto` | `on`/`off` 강제 |
| `runtime_scale`, `latency_scale` | 1.0 | 차기 과제 SW 증가 |
| `task_adjustments` | {} | task별 `scale` 또는 `delta_ms` |
| `task_latency` | {} | **SW task latency** (ms). 우선순위: `task_latency` → profile `start_latency_{stat}` → `start_latency_mean` → jitter → edge latency |
| `ip_overhead` | {} | IP별 직렬 SW overhead (driver setup/IRQ, ms). 해당 stage의 SW에 포함 |
| `rt_margin`, `output_margin` | 0.25 | 25% rule |
| `mfc_dual` | `auto` | `on`/`off` |
| `interval_tolerance` | 1e-3 | ±0.1% |
| `shared_cpu` | false | true면 모든 SW가 하나의 CPU resource를 공유 |
| `cpu` | cluster 1, 2000 MHz, 0.80 V | CPU power model |
| `include_whatif` | false | mean/max × EIS on/off × scale 1.0~1.5 grid |

## 5. Power / BW

- CPU power: `coeff[cluster] × f × V² × util` (Linux EM). coeff는 ip-cpu-s5e9965 profiler 값 `[449, 449, 505, 1127] µW/MHz/V²`. cluster/freq/volt는 **가정값**이다.
- HW power: IP `unit_power × (V/710)² × cores`. `unit_power=0`인 IP는 `zero_power_ips`로 보고한다.
- BW: HW DMA와 SW DMA(`mpeg_writer`, `storage_write` 등)를 분리한다. BW power는 MIF `bw_power_coeff`를 사용한다.

## 6. 실행

```bash
# API + UI
uv run uvicorn scenario_db.api.app:app --reload
cd ui && npm run dev   # http://localhost:5173/#/timing?scenario=uc-camera-recording&variant=cam-rec-r1-uhd30-vdis

# fixture fleet 보고서 (DB 불필요)
uv run python scripts/timing_budget_report.py --statistic max \
  --dvfs-table db_fixtures_Exynos2600_S26Plus/00_hw/dvfs-exynos2600-sample-v0.yaml --out output/timing-budget
```

## 7. 가정과 한계

- `dvfs-exynos2600-sample-v0.yaml`에서 MIF만 실제 CSV 기반이다. CAM/INTCAM/INT/APV는 **SYNTHETIC**이고 CSIS는 제외했다. 사내 table로 교체해야 한다.
- fixture SW runtime/latency 대부분이 `assumed`이다. 실측 profile을 import하면 `source`가 바뀐다.
- 120 fps 이상에서 NRT batch 처리(여러 frame 묶음)는 모델링하지 않았다. 해당 variant는 `fail`로 나온다.
- CPU cluster/freq/volt는 task별 실측이 아니라 단일 가정값이다.
