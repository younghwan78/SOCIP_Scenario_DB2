# 실측(Measurement) 데이터 Import 예제

실증/실측 데이터를 ScenarioDB 에 넣기 전에, **어떤 형식으로 import 하는지**를
실제로 돌려볼 수 있게 만든 예제 키트입니다.

> 핵심: DB 가 직접 받는 형식은 **canonical `evidence.measurement` YAML 하나**뿐.
> 거기에 도달하는 경로가 두 가지(자동 변환 A / 직접 작성 B)입니다.

```mermaid
flowchart LR
  subgraph Capture["측정 현장 산출물 (raw)"]
    M["meta.yaml<br/>캡처 메타 + 변환 지시"]
    P["rail_power_by_run.csv<br/>run × rail 의 V/mA/mW"]
  end
  M --> CLI["Path A<br/>meas_import.cli (rail_long)"]
  P --> CLI
  CLI --> Canon[("canonical<br/>evidence.measurement.yaml")]
  H["Path B<br/>손으로 작성한 canonical yaml"] --> Canon
  Canon --> ETL["etl.loader"] --> DB[("PostgreSQL<br/>evidence 테이블")]
```

## 실측 데이터의 실제 구조 (이 예제가 모델링하는 것)

실측 벤치는 rail 별로 **세 값**을 내보냅니다 — `Voltage(V)`, `Current(mA)`, `Power(mW)`.
주 지표는 **전류(mA)**, 전압(V)은 **의도한 전압이 인가됐는지 검증**용이라 셋 다 보존합니다.

| 측정 방법론 | 데이터 모델 반영 |
|---|---|
| 15/30초 구간 측정 → rail별 평균 1값 | CSV 한 행 = 한 run × 한 rail (파형 아님) |
| 보통 3회 반복, 특이 시나리오는 1회 | `provenance.sample_count` = run 수, `MeasuredKpi.n` = run 수 |
| rail 명/개수가 과제마다 다름 | `vdd_power` = free-form dict (고정 rail 리스트 없음) |
| GPU 등 gating 된 rail 존재 | near-zero 값 그대로 허용 |

> **두 "count" 구분** — `MeasuredKpi.n`/`provenance.sample_count` 는 **반복 측정(run) 횟수**입니다.
> "3번 측정해 평균" = `sample_count: 3`, "1번만" = `sample_count: 1`. (파형 내부 샘플 수가 아님)

| 구분 | Path A — 자동 변환 | Path B — 직접 작성 |
|---|---|---|
| 입력 | `meta.yaml` + `rail_power_by_run.csv` | canonical YAML 직접 작성 |
| 도구 | `meas_import.cli` 가 run 간 통계 산출 | 사람이 통계치 기입 |
| 적합 | run별 rail 측정 raw 보유 | 외부 리포트 요약만 보유 |
| 산출물 | `evidence.measurement` YAML (동일 스키마) | `evidence.measurement` YAML (동일 스키마) |

대상 참조(main DB 적재됨): `project=proj-sm-s947b`, `scenario=uc-camera-recording`, `variant=cam-rec-r1-uhd30-vdis`.

---

## 디렉터리

```
examples/measurement-import/
├─ path-a-capture/
│  ├─ meta.yaml                 # 캡처 메타 + rail_long 변환 지시
│  └─ rail_power_by_run.csv     # run(3) × rail(16) = 48행, V/mA/mW
├─ path-b-canonical/
│  └─ meas-example-canonical.yaml
└─ _generated/                  # Path A 변환 결과 (git 미추적)
```

ETL 로더는 `DATABASE_URL` 을 직접 읽으므로(자동 `.env` 로드 아님) 적재 전 1회 설정:

```powershell
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:15432/scenario_db"
```

---

## Path A — 캡처 → canonical 자동 변환 (rail_long)

CSV 헤더: `run,rail,voltage_v,current_ma,power_mw` (한 행 = 한 run × 한 rail).

```powershell
uv run python -m scenario_db.meas_import.cli `
  --meta examples/measurement-import/path-a-capture/meta.yaml `
  --out  examples/measurement-import/_generated --strict
```

CLI 가 **run 간(n=run 수)** 으로 자동 산출하는 것:

| 산출 필드 | 내용 |
|---|---|
| `vdd_power.{rail}` | `{voltage_v, current_ma, power_mw, std_mw}` — rail별 run 평균 + 표준편차 |
| `kpi.total_power_mw` | run별 전체 rail 합 → run 간 mean/std/ci_95/n |
| `cpu_breakdown[]` | `meta.power.rails` 로 매핑한 클러스터(BIG/MID/LIT)의 run 간 합 |
| `artifacts[].sha256` | `artifacts[].source` 로컬 파일 해시 |

> `total_power_rails: []` 면 전체 rail 합. 이때 run마다 rail set이 동일해야 합니다.
> 측정 중 일부 rail이 빠지거나 추가될 수 있으면, 비교 가능한 rail만 `total_power_rails`에 명시하세요.
> `meta.power.rails` 의 cpu_cluster 매핑은 **선택** — 지정 안 한 rail 은 `vdd_power` 테이블에만 남습니다.

DB 적재:

```powershell
uv run python -m scenario_db.etl.loader examples/measurement-import/_generated
```

---

## Path B — canonical YAML 직접 작성 → 적재

`path-b-canonical/meas-example-canonical.yaml` 이 DB 가 받는 최종 형식이며, Path A 출력과 **스키마 동일**.

핵심 규약:

- `kind: evidence.measurement`, `execution_context.method: measurement` — Measurement 축 분류
- `vdd_power.{rail}` = rail별 **V/mA/mW**(+std). rail 명/개수 과제별 가변 → free-form dict
- KPI·`cpu_breakdown[].power_mw` 는 **run 간 MeasuredKpi**(`{mean,std,ci_95,n}`). n = `sample_count`
- `artifacts[]` 는 **path + sha256 만** DB 기록(Tier3 실파일은 file-store)

```powershell
uv run python -m scenario_db.etl.loader examples/measurement-import/path-b-canonical
```

---

## Perfetto-derived 데이터: 무엇을 올리고 무엇을 보여주나

perfetto 추출은 **별도 분석 도구**에서 하고, 그 **결과(요약 다이제스트)만** canonical 에 기입합니다
(Path B 예제가 power + perfetto-derived 를 한 evidence 에 합친 완성형). raw trace 는 DB 미저장 —
`artifacts[]` 의 path+sha256 으로만 추적합니다.

**무엇을 올리나 (계약)** — raw 슬라이스/스레드가 아니라 **고정 논리키**로 큐레이션해야 교차 비교됨:

| canonical 필드 | 내용 | 키/단위 |
|---|---|---|
| `cpu_breakdown[].freq_residency` | 시간가중 주파수 점유율 `{freq_mhz, ratio(합≈1), time_ms}` | per-cluster |
| `cpu_breakdown[].avg_freq_mhz` | 점유율 가중 평균 주파수 | per-cluster |
| `cpu_breakdown[].util_pct` | 클러스터 사용률 | per-cluster % |
| `sw_task_timing[]` | 핵심 task `{mean/p50/p95/max_ms, samples, count_per_frame}` | **논리 task명** (raw 스레드명 ❌) |
| `kpi.frame_latency_ms` | 프레임 분포 `{mean, p95, n=프레임수}` | 예산(33.3ms@30fps) 대비 |
| `timeline_events[]` | frame_drop / thermal_step 등 sparse 이벤트 | t_ms |

**무엇을 보여주나** (대시보드 Measurement 뷰 — 대부분 이미 렌더):

| 데이터 | 표현 | 답하는 질문 |
|---|---|---|
| freq_residency | 클러스터별 stacked bar (CPU/Freq 탭) | DVFS가 어디 머무나·throttle 거동 |
| util_pct + avg_freq | 클러스터 health | 어느 클러스터 포화 |
| sw_task_timing | task p95 막대 + per-frame 호출수 (SW Timing 탭) | 프레임당 병목 task |
| frame_latency p95 | 예산선 대비 | 30fps 예산 초과·jank |
| 동일 키 delta | meas↔sim / SW123↔SW130 | 정합·회귀 |

예제 질의 (적재 후):

```powershell
# BIG 클러스터 최고주파 점유율 + eis_warp p95
uv run python -c "import os,json; from sqlalchemy import create_engine,text; e=create_engine(os.environ['DATABASE_URL']); c=e.connect(); cb=c.execute(text(\"select cpu_breakdown from evidence where id='meas-example-pathb-uhd30-vdis-20260614'\")).scalar(); big=[x for x in cb if x['cluster']=='BIG'][0]; print('BIG top freq bin:', sorted(big['freq_residency'], key=lambda b:-b['ratio'])[0]); st=c.execute(text(\"select sw_task_timing from evidence where id='meas-example-pathb-uhd30-vdis-20260614'\")).scalar(); print('eis_warp p95_ms:', [t for t in st if t['task']=='eis_warp'][0]['p95_ms'])"
```

---

## 적재 검증 (DB 조회)

```powershell
uv run python -c "import os; from sqlalchemy import create_engine,text; e=create_engine(os.environ['DATABASE_URL']); c=e.connect(); rows=c.execute(text(\"select id, (kpi->'total_power_mw'->>'mean') tp, jsonb_array_length(coalesce(cpu_breakdown,'[]')) clusters, (select count(*) from jsonb_object_keys(vdd_power)) rails from evidence where id like 'meas-example-%' order by id\")).all(); [print(r) for r in rows]"
```

기대 결과 — 두 행 (rails=16, clusters=3):

```
('meas-example-patha-uhd30-vdis-20260614', '675.222', 3, 16)
('meas-example-pathb-uhd30-vdis-20260614', '675.222', 3, 16)
```

특정 rail 의 V/mA/mW 확인:

```powershell
uv run python -c "import os; from sqlalchemy import create_engine,text; e=create_engine(os.environ['DATABASE_URL']); c=e.connect(); print(c.execute(text(\"select vdd_power->'B5_6S1_VDD_CAM_L' from evidence where id='meas-example-pathb-uhd30-vdis-20260614'\")).scalar())"
```

대시보드: **Evidence Dashboard → Evidence Method = `Measurement`** 로 전환 후 위 scenario/variant 선택.

## 정리 (예제 데이터 삭제)

```powershell
uv run python -c "import os; from sqlalchemy import create_engine,text; e=create_engine(os.environ['DATABASE_URL']); c=e.connect(); c.execute(text(\"delete from evidence where id like 'meas-example-%'\")); c.commit(); print('deleted example evidence')"
```

---

## 실제 실측 도입 시 체크리스트

1. `project_ref`/`scenario_ref`/`variant_ref` 를 실제 대상 ID 로 교체(반드시 사전 적재).
2. `provenance.sample_count` = 반복 측정 횟수(보통 3, 특이 시나리오 1), `duration_per_sample_s` = 구간 길이.
   - `confidence_level` 을 주면 CI 가 그 신뢰수준으로 계산되고(`0.90`/`0.99` 등) `ci_level` 에 기록됩니다. 비우거나 `0.95` 면 기존 95% 구간(키만 `ci_95`).
3. rail CSV 는 과제별 rail 명/개수 그대로 — 고정 리스트 가정 금지. `power.rails` 의 클러스터/`domain` 매핑만 과제에 맞게.
   - **대시보드 "Current by domain" 롤업**은 rail 의 `domain` 으로 묶습니다. meta `power.rails.{rail}.domain`(→ canonical `vdd_power.{rail}.domain` 로 전파) 또는 Path B 에서 직접 기입. **부분 선언이면 충분** — 이름 휴리스틱(CPUCL→CPU, CAM→CAM, MEM/DRAM/SRAM→MEM…)이 틀리거나 모호한 rail 만 적으면 됩니다. 별도 설정 파일 불필요.
4. 전압(V)은 인가 검증용으로 같이 적재. 전류(mA)가 주 지표.
5. raw artifact(CSV 등)는 file-store 에 두고 YAML 에는 `path` + `sha256` 만.
6. 같은 캠페인을 여러 번 측정하면 Path A(rail_long)로 자동 집계 → 휴먼 에러/재현성 우위.

> 참고: 대시보드 측정 뷰(`vdd_power_rows`)는 `voltage_v`, `current_ma`, `power_mw`, `std_mw`
> triplet과 legacy `mean_mw`/`p95_mw` 형식을 모두 표시합니다.
