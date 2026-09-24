# SW timing margin (timing-aware clock margin)

기존 rule of thumb — "SW가 frame의 25%를 쓴다고 보고 HW time ≤ 75% × frame period (30fps: 24.75 ms)로 clock 설정" — 을 pipeline timeline으로 대체한다. 이전 과제 SW task runtime · SW event latency · IP별 직렬 SW overhead와 차기 과제 SW 증가를 넣고, scenario별로 **실제 필요한 margin**을 구한다. Read-only 분석이며 evidence/fixture를 저장하지 않는다.

코드: `src/scenario_db/sim/sw_margin.py` · API `POST /api/v1/simulation/sw-margin` · CLI `scripts/sw_margin_report.py`

## 정의

| 항목 | 정의 |
|---|---|
| margin m | 기존 clock margin. `required_clock = pixels × fps / (1 − m) / ppc` → HW time = `(1 − m)(1 + h_blank) × period` |
| rule | m = 0.25 (옵션 `rule_margin`) |
| C1 frame cycle | resource별 1 frame busy time ≤ period. HW time + **직렬 SW overhead**(driver setup, IRQ completion), 같은 CPU resource의 SW task 합 포함. m에 단조 |
| C2 latency | sensor frame 시작 → sink 완료 ≤ `latency_budget_frames × period`. 기본 대상 = display sink(`constraint_type: sink`), 그 외 sink는 `sink_budget_frames`로 지정 (예: `storage_write: 4`) |
| required margin m* | C1·C2를 만족하는 feasible 구간(상한까지 연속)의 하한. grid scan(0.02) + bisection(0.001). 공유 CPU contention 때문에 C2는 m에 비단조일 수 있어, 하한 아래의 고립 feasible 점은 `isolated_feasible`로만 보고 |
| verdict | `rule_over_provisioned` (m* < rule − 5%p) · `rule_adequate` · `rule_insufficient` · `clock_unreachable` (m* > `practical_margin_limit`, 기본 0.5: clock으로 해결 불가 — binding이 SW/CPU면 SW 경로, HW resource load면 multi-stream 공유 IP 과부하) · `infeasible` |
| growth headroom | rule margin에서 SW runtime+overhead를 몇 배까지 늘려도 C1·C2를 만족하는지 (0.05 step, 연속 구간) |
| critical path | 최악 sink frame의 latency를 HW / SW / 직렬 overhead / wait으로 분해 (합 = latency) |

## 입력

| 입력 | 소스 | 비고 |
|---|---|---|
| SW task runtime min/mean/max | variant `node_configs.<task>.sw_timing` 또는 `config.sw_timing_projection` (이전 과제 측정 → 차기 mapping, `sw_projection.py`) | `statistic`: min/mean/max |
| SW event latency | `start_jitter_mean_ms` / projection `event_latency` → timeline edge latency | `growth.latency_scale` |
| IP 직렬 SW overhead | `options.ip_overhead{node: {setup, completion}}`, `default_ip_overhead` (sensor 동기 OTF 그룹 제외 HW에 적용) | 이전 과제 Perfetto: shot/trigger→HW start, HW done→IRQ 처리 종료 |
| 차기 SW 증가 | `growth.runtime_scale`, `overhead_scale`, `task_adjustments{task: scale|delta_ms}`, `extra_tasks[{id, after, before, runtime, resource_id}]` | extra task는 기존 edge `after→before` 사이에 gating task로 삽입 |
| 분포 | `monte_carlo_samples` (API ≤ 50), triangular(min, mean, max), sample당 모든 frame 동일값(지속 조건) | p50/p90/p99, rule coverage |
| DVFS | `dvfs_table_ref` / `dvfs_tables` | 없으면 clock 연속·전압 고정 → power Δ = 0 |

## 사용

```bash
# CLI (fixture, DB 불필요)
uv run python scripts/sw_margin_report.py --statistic mean max \
  --ip-overhead-ms 0.5/1.0/2.0,0.3/0.6/1.5 --sink-budget storage_write=4 --out output/sw-margin
```

```json
POST /api/v1/simulation/sw-margin
{"scenario_id": "uc-camera-recording", "variant_id": "cam-rec-r1-uhd30-vdis",
 "options": {"statistic": "max", "rule_margin": 0.25,
   "default_ip_overhead": {"setup": {"min_ms": 0.5, "mean_ms": 1.0, "max_ms": 2.0},
                           "completion": {"min_ms": 0.3, "mean_ms": 0.6, "max_ms": 1.5}},
   "growth": {"runtime_scale": 1.2,
     "extra_tasks": [{"id": "next_ai_scene", "after": "post_irta", "before": "mtnr",
                      "runtime": {"min_ms": 1.5, "mean_ms": 2.0, "max_ms": 3.0}}]},
   "constraints": {"latency_budget_frames": 3, "sink_budget_frames": {"storage_write": 4}},
   "monte_carlo_samples": 20},
 "config_profile_ref": "simcfg-proj-sm-s947b-v1"}
```

출력: `required` (m*, HW time limit, binding constraint, clocks, power) · `rule` (verdict, gap, latency/jitter, resource load) · `growth_headroom_at_rule` · `growth_sweep` · `critical_path` · `per_ip_plan` (IP별 C1 floor + C2 공통 lift) · `monte_carlo` · `warnings`.

## 한계

- Pipeline SW task는 CPU resource 단위로만 경쟁 (core affinity, 우선순위, preemption, DVFS of CPU 미모델). `resource_id`로 core 분리 표현
- per-frame 변동은 Monte Carlo가 sample 단위 지속값으로 근사 (frame별 spike, tail 확률 아님)
- `pre_me_rta`처럼 HW를 포함한 aggregate stage는 SW growth가 stage 전체에 적용됨 (경고 출력)
- 고fps(120/240/480/960)는 per-frame SW 모델이 batch 처리를 표현하지 못해 CPU_CAMERA C1 위반 → `batch_size` 모델 필요
- Latency budget 기본 3 frame은 가정값. 과제 spec(preview latency 등)으로 지정 필요
- DVFS table 없으면 power 절감/증가는 0으로 표시 (clock만 변화)
