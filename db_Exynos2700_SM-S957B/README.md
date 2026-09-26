# db_Exynos2700_SM-S957B — Exynos2700 (S5E9975) · SM-S957B

DB 적재 원본. `scripts/dev_up.ps1`이 이 폴더를 ETL로 적재한다.

| 경로 | 관리 방식 | 수정 방법 |
| --- | --- | --- |
| `00_hw/` `00_sensor/` `01_sw/` `02_definition/` | **생성물** (`authoring/`에서 compile). 직접 수정 금지 | `authoring/platforms/exynos2700/`, `authoring/projects/sm-s957b/` 수정 → dev_up (자동 sync) |
| `measurements/<variant>/meta.yaml` + `rail_power_by_run.csv` | **사람이 관리** (실측 입력) | 값 수정 → `provenance.revision` +1 → dev_up |
| `03_evidence/meas-*.yaml` | 생성물 (`scripts/import_measurements.py`) | measurements/ 입력을 수정 |

- IP / sensor / board lineup 문서는 2600과 공유하지 않는다 (`ip-*-s5e9975`, `sensor-*-s5e9975`,
  `sensortiming-*-s5e9975`, `board-lineup-s5e9975`, SW profile `sw-vendor-v1.2.3-s5e9975`). 과제별 사양/설정 차이는 authoring patch로 넣는다.
- 현재 `measurements/`는 **DUMMY** 값이다 (`provenance.device_id: DUMMY`). 2600 synthetic 실측과
  simulation을 축척한 값이며 구조 확인·검증용이다. 사내 캡처로 교체한다.

## 실측 입력 → DB

`meta.yaml`은 [Measurement Import Guide](../docs/guides/measurement/measurement-import-guide-ko.md)의 형식이다.

| 데이터 | meta.yaml 위치 | 결과 evidence |
| --- | --- | --- |
| Power (rail별 V/mA/mW, run 반복) | `power:` + `rail_power_by_run.csv` | `kpi.total_power_mw`, `vdd_power`, `power.rail*` |
| BW | `metric_observations:` `bandwidth.total` (scenario), `bandwidth.read/write` (ip) | `metric_observations` |
| SW task timing (요약값) | `sw_task_timing:` task별 min/mean/p95/max/samples | `sw_task_timing` |
| SW task timing (trace) | `perfetto:` + trace 파일 | `sw_task_timing`, `cpu_breakdown` |
| Frame latency / fps | `kpi:` | `kpi` |

갱신:

1. `measurements/<variant>/meta.yaml` 또는 CSV 수정
2. 같은 파일의 `provenance.revision`을 1 올림 (올리지 않으면 conflict로 멈춘다 — 실수로 덮어쓰기 방지)
3. `powershell -ExecutionPolicy Bypass -File scripts\dev_up.ps1 -NoUi`
   (또는 `uv run python scripts/import_measurements.py db_Exynos2700_SM-S957B --strict` 후 ETL)

새 측정은 폴더를 추가하고 `id`를 새로 정한다 (예: `...-evt1`). 같은 id = 같은 측정의 정정본이다.
