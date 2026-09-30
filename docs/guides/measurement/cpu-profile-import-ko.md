# CPU topology · CPU profile import 가이드

사내 perfetto / simpleperf / profiler 출력 형식이 도구·버전마다 달라서, **파서 코드 대신 `meta.yaml` 설정으로 컬럼·카운터 이름을 매핑**한다. 새 형식이 오면 코드 수정 없이 `pmu.table.sources`만 추가/수정한다.

## 1. SoC CPU topology (`power_model_params.cpu`)

cluster 수·구성은 SoC마다 다르므로 데이터로 둔다. 예시: `examples/cpu-topology/pmp-exynos2{6,7,8}00-cpu-example.yaml` (수치는 SYNTHETIC).

| 필드 | 의미 |
|---|---|
| `clusters[].name` | cluster 이름. 실측 `cpu_breakdown`(rail rollup) cluster 이름과 같게 두면 예측↔실측 `power.cluster`가 join된다 |
| `core_type` | 마이크로아키텍처 id (과제 간 재사용 키, 예: MID_LF / MID_HF / BIG_LF / BIG) |
| `cores`, `cpus` | core 수, trace의 logical CPU id (cpus 개수 = cores) |
| `opps[]` | `{mhz, mv, mw_per_core}` — core 1개 100% util 동적 전력(EM table). 없으면 `coeff_uw_per_mhz_v2` |
| `leakage` | `mw_per_core_at_ref × (V/ref_mv)^exponent` |
| `rail` | 측정 rail 이름 (vdd_power 키로 사용) |
| `dsu` | DSU OPP/leakage/rail |

SoC별 구성 (사내 기준):
- Exynos2600: DSU, MID_LF×3, MID_LF×3, MID_HF×3, BIG×1
- Exynos2700: DSU, MID_LF×4, MID_HF×4, BIG_LF×1, BIG×1
- Exynos2800: DSU, MID_HF×3, MID_HF×3, BIG_LF×2, BIG×1

## 2. CPU profile import (`pmu.format: table`)

예시 번들: `examples/measurement-import/cpu-profile-sample/` (simpleperf-like counter dump, perfetto SQL export 형태의 freq/idle residency).

```yaml
pmu:
  format: table
  window: {duration_s: 30, fps: 30}     # 또는 {frames: 900} → counter를 frame당 값으로 정규화
  cpu_map: {"0-3": MID_LF, "4-7": MID_HF, "8": BIG_LF, "9": BIG}   # 없으면 perfetto.cpu_to_cluster
  table:
    sources: [...]
```

### source 공통
| 키 | 설명 |
|---|---|
| `file` | meta.yaml 기준 상대 경로 |
| `kind` | `counters` / `freq_residency` / `idle_residency` |
| `delimiter` | 생략 시 자동 판별 (`,` `\t` `;` `|`) |
| `header_contains` | 앞부분 설명 텍스트를 건너뛰고, 이 이름의 컬럼이 있는 줄을 header로 사용 |
| `columns` | header 없는 파일의 컬럼 이름 |
| `comment_prefix` | 무시할 줄 접두어 (기본 `#`) |
| `filter` | `{컬럼: regex}` 모두 만족하는 행만 사용 |
| `cpu` / `cluster` | 행의 위치 scope. `{column: cpu}`, `{column: x, regex: "cpu(\\d+)"}`, `{value: MID_HF}` |
| `task` + `task_rules` | thread/process 이름 → 논리 task (`{match: regex, task: eis}`), 여러 thread는 합산 |
| `unmapped_task` | `other`(기본, `(other)`로 합산) / `keep`(원래 이름) / `drop`(버림, warning) |

숫자의 천단위 `,`와 `%`는 허용한다.

### kind별
- `counters`
  - `layout: long`: 행마다 counter 1개 → `counter_column`, `value_column`
  - `layout: wide`: counter가 컬럼 → `counters`의 alias가 컬럼 이름
  - `counters`: 표준 이름 → 도구 이름 목록. 표준: `cycles`, `instructions`, `stall_cycles`, `bus_access`(× `bytes_per_access`), `bus_bytes`
- `freq_residency`: `freq_column`, `freq_unit`(mhz/khz/hz/ghz), `value_column`(시간, 단위 무관)
- `idle_residency`: `state_column`, `value_column`, `states: {regex: active | clock_gated | power_gated}`

### 생성되는 observation (frame당)
| metric | scope |
|---|---|
| `cpu.cycles_pf`, `cpu.instructions_pf`, `cpu.stall_cycles_pf`, `cpu.bus_bytes_pf` | `task_cluster` (`task@cluster`), `cluster` |
| `cpu.freq_residency` | `cluster_freq` (`cluster@MHz`) |
| `cpu.active_ratio`, `cpu.clock_gated_ratio`, `cpu.power_gated_ratio` | `cluster` |

topology의 `cpu.dsu.name`과 일치하는 cluster 데이터는 DSU로 사용한다(기본 이름 `DSU`). perfetto digest(`perfetto.cpu_to_cluster`)가 만든 `cpu_breakdown[].freq_residency`도 residency가 없는 cluster에 자동 보충된다. 주파수는 유한한 양수, residency는 유한한 음이 아닌 값이어야 하며, 비어 있지 않은 residency의 합은 양수여야 한다.

검증만: `uv run python -m scenario_db.meas_import.cli --meta <meta.yaml> --out <dir> --strict` 후 report의 warning(미매핑 thread/counter/state, cpu_map 누락)을 확인.

## 3. 시뮬레이션에서 사용

```yaml
config:
  power_params_ref: pmp-exynos2700-v1     # cpu topology 포함
  cpu_profile_ref: <measurement evidence id>
```

- 측정된 배치 그대로: task×cluster `cycles × Σ r_l·(P_core(f_l)/f_l)` + cluster leakage × `(1 − power_gated_ratio)` + DSU(`active_ratio` 미측정 시 가장 바쁜 cluster의 `1 − cg − pg`).
- mapping되지 않은 cycle은 `(other)`로 남는다(버리지 않음).
- 다른 variant/과제의 profile도 쓸 수 있고(차기 과제 base), 이 경우 warning이 남는다.
- 결과: `power_breakdown.cpu.{by_cluster, by_task, clusters(dynamic/static/mean_mhz/gating), dsu}`, rail은 topology `rail`.

## 4. CPU 배치 · 주파수 what-if (`#/cpu`, `POST /api/v1/cpu/whatif`)

측정 profile의 task별 frame당 수요를 기준으로, 시계열 없이 배치/주파수 조합을 평가한다.

- 시간 모델 (stall 분리): 측정 cluster c0의 평균 주파수 f0 기준
  `core = cycles − stall`, `stall_ms = stall / f0` →
  대상 cluster c, 주파수 f, SW growth g에서 `t = g·core·ipc_rel(c0)/ipc_rel(c)/f + g·stall_ms`.
  core type별 IPC 비율은 topology `ipc_rel`.
- cluster별 OPP: task budget(`budgets_ms`, Timing Budget의 SW budget), `Σt ≤ util_cap × cores × period`, `t ≤ period`를 만족하는 **최소 전력 OPP** (같은 전압의 상위 OPP가 더 유리하면 그것).
- static: `cores × leak(V) × (active + idle × (1 − power_gating_eff))`, DSU는 가장 바쁜 cluster 비율.
- CPU BW: `bus_bytes × g × fps × cpu_bw_scale` (L3/SLC 변경 등은 배율로).
- 결과: 측정 placement(측정 DVFS 그대로 / 이상적 DVFS), 후보 배치별 전력·Δ·최소 slack·CPU BW, power–slack Pareto(★).
- 다른 SoC로 이동: `base_power_params_ref`(측정 SoC topology)를 주면 cluster 이름 → 같은 `core_type` cluster로 대응.

시뮬레이션에서는 profile이 있으면 cluster별 CPU BW가 `cpu.<cluster>`/`BUS` pseudo DMA로 BW 합계·BW power·MIF 비교에 들어간다 (`include_cpu_bw: false`로 끔).

한계(사내 보정 대상): stall 시간의 주파수 무관 가정, core type별 단일 IPC 비율, task는 한 cluster에서 실행.
