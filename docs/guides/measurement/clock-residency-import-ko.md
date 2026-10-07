# Clock 분포(residency) import 가이드 — CPU cluster · DSU · GPU

측정 중 각 clock domain이 어떤 주파수에 얼마나 머물렀는지를 evidence에 저장하고, `#/calibration`, CPU what-if, 보고서 ④에서 보여 준다.
확장 설계(raw manifest, 조합 탐색 CPU 모델, 3-pass counter, GPU power): [design/clock-residency-and-raw-data-extension-ko.md](../../design/clock-residency-and-raw-data-extension-ko.md)

코드: `meas_import/clock_residency.py` (import), `api/services/clock_residency.py` (화면·보고서 공통 해석 규칙), `reporting/clock_section.py` (보고서).

## 1. 무엇을 저장하나

| 기준 | 의미 | 쓰는 곳 |
|---|---|---|
| 전체 (`wall`) | capture 전체 시간 중 governor 주파수 비율 | leakage (전압), governor 동작 확인 |
| running (`active`) | idle(WFI · power down)을 뺀 **동작 시간** 중 주파수 비율 | **dynamic power** (cycle 가중 energy/cycle), stall 시간 환산 |

governor가 idle 동안 낮은(또는 높은) 주파수에 머무르면 두 분포가 달라진다. running 분포가 없으면 전체 분포로 근사한다(기존 동작).

| observation | scope (ref) | 비고 |
|---|---|---|
| `cpu.freq_residency` | `cluster_freq` (`MID_LF0@1000`, `DSU@900`) | 기존 |
| `cpu.freq_residency_active` | `cluster_freq` | 신규 · CPU power가 있으면 사용 |
| `gpu.freq_residency`, `gpu.freq_residency_active` | `gpu_freq` (`GPU@356`) | 신규 |
| `gpu.active_ratio`, `gpu.clock_gated_ratio`, `gpu.power_gated_ratio` | `gpu` (`GPU`) | 신규 |
| `clock.residency_pass_jsd` | `clock_domain` (`cpu/MID_LF0`, `gpu/GPU`) | PMU pass 간 분포 차이 (capture 품질) |

## 2. Table export로 import (`pmu.format: table`)

`freq_residency` / `idle_residency` source에 세 키가 추가됐다 (기본값이면 기존과 동일).

| 키 | 값 | 설명 |
|---|---|---|
| `domain_class` | `cpu`(기본) · `gpu` | `gpu`는 `cluster` scope(= domain 이름)만 허용 |
| `basis` | `wall`(기본) · `active` | `active` = running 시간만 집계한 export |
| `group` | 예: `pass1` | 같은 capture의 부분(15 s × 3 PMU pass). 합산하고, group 사이 JSD를 품질 지표로 남김 |

DSU는 `domain_class: cpu` + `cluster: {value: DSU}`(또는 domain 컬럼)로 넣는다 — 기존처럼 CPU profile의 DSU로 쓰인다.

예시 (사외 Exynos2600, SYNTHETIC): `examples/measurement-import/clock-residency-e2600/<variant>/` — `scripts/generate_clock_residency_example.py`로 생성.

```yaml
pmu:
  format: table
  cpu_map: {"0-2": MID_LF0, "3-5": MID_LF1, "6-8": MID_HF, "9": BIG}
  table:
    sources:
      - {file: cpu_freq_residency.csv, kind: freq_residency, group: pass1, filter: {pass: "^1$"},
         cpu: {column: cpu}, freq_column: freq_khz, freq_unit: khz, value_column: dur_ns}
      - {file: cpu_freq_residency_running.csv, kind: freq_residency, basis: active, group: pass1, filter: {pass: "^1$"},
         cpu: {column: cpu}, freq_column: freq_khz, freq_unit: khz, value_column: dur_ns}
      - {file: dsu_gpu_freq_residency.csv, kind: freq_residency, domain_class: gpu, filter: {domain: "^GPU$", basis: "^wall$"},
         cluster: {column: domain}, freq_column: freq_khz, freq_unit: khz, value_column: dur_ns}
      - {file: gpu_idle_residency.csv, kind: idle_residency, domain_class: gpu, cluster: {column: domain},
         state_column: state, value_column: dur_ns, states: {busy: active, clock_gated: clock_gated, power_off: power_gated}}
```

pass별로 파일이 따로 있으면 `filter` 대신 source를 pass마다 하나씩 두고 `group`만 다르게 주면 된다.

### running(active) export 만드는 perfetto SQL

`meas_import/perfetto_digest.py`의 `SQL_CPU_ACTIVE_RESIDENCY`를 그대로 trace_processor에서 실행해 CSV로 저장하면 된다
(cpufreq span × cpuidle span을 CPU별 `SPAN_JOIN`, cpuidle 값 4294967295 = running). trace_processor v50 기준으로 검증.

## 3. Perfetto trace에서 직접 (`perfetto:` section)

```yaml
perfetto:
  trace: capture.pftrace
  cpu_to_cluster: {0: MID_LF0, 1: MID_LF0, 2: MID_LF0, ...}
  cpu_active_residency: true            # cpu.freq_residency_active
  clock_domains:
    - {name: GPU, domain_class: gpu, tracks: [gpufreq], freq_unit: khz,
       utilization_track: gpu_util, utilization_scale: 100}   # 선택: busy % track → running 분포 · gpu.active_ratio
    - {name: DSU, domain_class: cpu, tracks: [dsu_freq], freq_unit: khz}
```

- `tracks`는 counter track 이름(정확히 일치). 여러 개를 주면 sample이 있는 첫 track을 쓴다. track 이름은 kernel·driver마다 다르므로 trace에서 `select name from counter_track`로 확인.
- 같은 domain을 PMU table과 trace가 둘 다 주면 **PMU table만** 쓴다(주파수 bin이 섞이지 않게).

## 4. 화면 · 보고서

- `#/calibration` 상세 → **Clock 분포 — CPU · DSU · GPU** 카드: 요약 문장, domain별 분포 막대(연한 색 = 낮은 주파수), 평균·최빈·고 OPP·동작·pass JSD, 메모. 행 클릭 = 전체 vs running histogram. running/전체 기준 전환.
- 같은 화면 하단 **Clock 분포 비교 — 측정별**: scenario의 측정(variant · SW version)별 평균 주파수 heat table.
- `#/cpu` sweep의 **모델 확인**: 측정 분포(회색 전체 · 청록 running) + 측정 평균 + 모델(EAS 재현) MHz(빨간 점선).
- 보고서 ④ 실측 대조 아래 **Clock 분포 실측** 표, XLSX `Clock 분포` sheet.

### 메모 규칙 (`api/services/clock_residency.py`, `RULES_VERSION`)

CPU cluster 전부에 running 분포가 없으면 domain별 메모 대신 요약에 한 줄(“dynamic power는 전체 분포로 근사”)로 표시한다.

| code | 조건 | 의미 |
|---|---|---|
| `pass_divergence` | pass JSD > 0.05 | pass 사이 DVFS 동작이 다름 → 온도·부하 변화, capture 품질 확인 |
| `high_opp` | running(없으면 전체) 시간의 30% 이상이 fmax의 80% 이상 | 부하 집중·boost → CPU what-if 분산 검토 |
| `burst` | 동작 < 20% 인데 평균 ≥ fmax의 70% | 짧은 burst를 높은 clock으로 처리 (rate limit · uclamp_max 검토) |
| `idle_gap` | running 평균과 전체 평균 차이 ≥ 10% | idle 동안 다른 주파수에 머무름 (dynamic power는 running 기준) |
| `idle_domain` | 동작 < 0.5% | 거의 동작하지 않음 (분포는 idle 중 governor 값) |

fmax: CPU cluster · DSU = 같은 SoC의 `power_model_params.cpu`, GPU = IP catalog `capabilities.dvfs_model.max_freq_khz`. 모르면 고 OPP는 표시하지 않는다.

## 5. 새 clock domain 추가 (예: NPU)

1. `meas_import/clock_residency.py`의 `DOMAIN_CLASSES`에 `"npu": DomainClass("npu", "NPU", "npu_freq", "npu")` 추가
2. `models/evidence/metric_catalog.yaml`에 `npu.freq_residency`, `npu.freq_residency_active`, `npu.active_ratio` 등 추가
3. (선택) IP catalog `ip-npu-*`에 `capabilities.dvfs_model.max_freq_khz` — 고 OPP 판정에 사용

import · 화면 · 보고서는 registry를 따라 자동으로 표시된다.
