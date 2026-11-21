# SoC Simulation Contract

This document defines the minimum catalog metadata needed for SoC-level power,
bandwidth, performance, and timing simulation.

The contract has two scopes:

- **SoC fixture contract**: static YAML/catalog quality check for a SoC package.
- **Scenario readiness**: active scenario/variant check after routing, node config,
  external-device selection, and variant overlays are resolved.

The two scopes intentionally differ. A SoC may contain unused draft IPs with
borrowable simulation data, while an active scenario workload with missing `ppc`
must still be blocked.

## Timeline Resource Identity

Verified against the scheduler and its capacity regression tests on 2026-09-06.

The scenario adapter treats each HW pipeline/task node as a distinct resource by
default. `hw_name` and `ip_ref` identify display/catalog information and do not
imply that two nodes share one physical execution resource. This matters for
composite ISP catalog entries used by several independent pipeline stages.

To model shared hardware, give its nodes the same `resource_id` (the legacy
`resource` key is also accepted). Use `resource_capacity` for capacity, defaulting
to one. All declarations of the same resource should use the same capacity.
SW task nodes have no implicit resource; provide one explicitly when modeling
CPU contention.

An OTF streaming group reserves each of its distinct resources once for the
group lifetime, including latency offsets. Reservations are shared with ordinary
tasks and other frames. A group acquires resources in sorted order and releases
them on completion. This is a conservative group reservation model; it does not
model a separate sub-frame hardware initiation interval.

Changing from display-name resource aliases to node resources changes historical
timeline/cadence values. Compare newly generated evidence under the same model;
existing persisted evidence is not rewritten. The regression tests check resource
capacity independently of the updated golden timing values. These checks do not
replace calibration against real hardware.

## Compute IP Requirements

Compute IPs are catalog entries used as HW workloads in simulation. Typical
categories are `camera`, `codec`, `compute`, `cpu`, `display`, `gpu`, and `npu`.

Each simulation-ready compute IP should provide `capabilities.sim` with at least
one mode or role-mode containing:

| Field | Required for | Rule |
| --- | --- | --- |
| `ppc` | performance/timing | Positive value is required for active workloads. |
| `unit_power_mw_mp` | core power | Positive value is preferred. Missing value is a warning and may be borrowed. |
| `dvfs_group` | clock/DVFS | Required directly or via SoC profile fallback. |
| `vdd` | voltage/power domain | Required for VDD alignment and power trace. |
| `hw_name` | display/debug | Required directly or inferred from IP id as fallback. |

Role-level mappings are allowed and are preferred for composite catalog entries
where one `ip_ref` represents multiple pipeline roles, for example `csispdp`,
`byrp`, `rgbp`, `yuvp`, and `mtnr` under a shared ISP catalog.

### Workload load models (`sim/load_models.py`)

A load model turns a workload's conditions into its effective `ppc`. The clock rule, timing and power
then run the same calculation. Models are registered in `LOAD_MODELS` (like `POWER_MODELS`). The mode
`ppc` applies, as before, unless a node opts in, in this order:

1. the variant's `node_configs.<node>.sim.load_model: <id>` (`none` opts out);
2. the scenario pipeline node's `load_model: {ref: <id>, ...coefficients}`. These are scenario-local
   coefficients, so the shared IP catalog, and every other scenario's input hash, stays unchanged.
   E2600 decoders use this with assumed values;
3. a catalog model whose `roles` lists the node's role (e.g. `roles: [decoder]`).

`codec-throughput-v1` (decoder / encoder):

```
cycles / frame = pixels / ppc_codec + bitrate_mbps x 1e6 / fps x cycles_per_bit
ppc_effective  = pixels / (cycles / frame)
```

```yaml
capabilities:
  sim:
    load_models:
      codec-throughput-v1:
        codecs:                        # per <CODEC>_<DEC|ENC> of properties.codecs
          AV1_DEC: {ppc: 1.0, cycles_per_bit: 0.5}
        derive: codec_limits           # or ppc_codec = max_resolution x max_fps / clock_mhz
        clock_mhz: 664                 # the clock the declared codec limits are reached at
```

- The codec is `sim.codec`, else the node's `codec`, else `design_conditions.codec` / `codec_mfc`
  (`H264`, `h.264`, `AV1_DEC` …; a `_DEC` / `_ENC` suffix sets the direction, else the node role).
  The bitrate is `sim.bitrate_mbps`, else `design_conditions.bitrate_mbps`; with no bitrate there is
  no entropy term.
- A node that opts in without the coefficients it needs is refused, naming the node and the codec key.
  There is no silent fallback to the mode `ppc`.
- The Timing Budget IP row carries `load_model` (`codec`, `direction`, `ppc_codec`, `ppc_source`,
  `bitrate_mbps`, `cycles_per_bit`, `entropy_cycles_per_frame`, `ppc_effective`, `ppc_mode`) when the
  node opts in.

### Domain load models (`sim/domain_loads.py`, D-03)

GPU, NPU and audio-DSP nodes have no `ppc` / clock rule, so the compute model gives them 0 mW
(`zero_power_ips`). A domain load model turns a declared work rate into an operating point, a busy
share and a power. Models are registered in `DOMAIN_MODELS`; today `util-vf-v1`:

```
work     = (mcycles_per_frame + mcycles_per_layer x input_layers)
           x (pixels / ref_pixels) ^ pixel_exponent x rate_hz        (or mcycles_per_s)   [Mcycle/s]
f        = freq_mhz | the node's dvfs.aud_freq_khz | governor: lowest table f with work / f <= target_util
util     = work / f                                                  (> 1: verdict fail)
dynamic  = util x coeff_uw_per_mhz_v2 x f x V(f)^2 / 1000            [mW]
static   = leak(V(f)) x (util + (1 - util) x (1 - idle_gated)),  leak(V) = mw_at_ref x (V / ref_mv) ^ exponent
```

Declarations merge in this order (later wins):

1. the IP catalog, read only: `power_model` coefficient (`dynamic_coeff_uw_per_mhz_v2` or
   `profiler_dynamic_coeff`), `vf_table` / `vf_table_sample`, `leakage` / `leakage_sample`, and the
   `dvfs_model` frequency table (`freq_table_khz`, `dvfs_table[].freq_core_khz`, `aud_qos_levels_khz`);
2. the scenario pipeline node `domain_load: {model, coeff_uw_per_mhz_v2, vf, leakage, freqs_mhz, ...}`:
   scenario-local assumptions, so the shared IP catalog and every other scenario's input hash stay unchanged;
3. the variant `node_configs.<node>.sim.domain_load` (this variant's work; `none` opts out).

- `rate_hz` defaults to the node's `sim.fps`, else the frame rate; `pixels` is the node's `sim.width x height`.
- The node's power goes into `power.hw_by_ip` and `power.domain_loads[node]` (`work_mcycles_s`, `freq_mhz`,
  `freq_by`, `util`, `dynamic_mw`, `static_mw`, `mw`, `feasible`, `value_source`, `basis`). A node timed by
  `sw_timing` (a GPU task) keeps its time in the chain, but its power is the domain load's, not CPU work.
- Exploration cases (DVFS · compression) keep it constant, like an assumed load; the exploration slice
  carries `domain_by_ip`, the report row `domain_mw`, and the sensitivity table one `domain:<node>` row.
- Opt-in: a node without a declaration computes as before (engine revision unchanged, listed under `OPT_IN`).
  E2600 game, display, video, audio, call and camera-AI scenarios declare assumed values; the recording
  scenario (inherited by E2700) and the shared IP catalog are not changed.

## External Device Requirements

Sensors and panels are not compute workloads. They should not require `ppc` or
unit power for core power simulation.

Sensor catalog metadata should provide mode-level source constraints:

| Field | Purpose |
| --- | --- |
| `sensor_size` | Source width/height and default shape propagation. |
| `sensor_fps` | Source frame period. |
| `sensor_format` | Source format and downstream default format. |
| `sensor_bitwidth` | MIPI/CSIS clock correction and bandwidth interpretation. |
| `sensor_mipi_speed` | CSIS source clock correction. |
| `sensor_pclk`, `sensor_line_length_pck` | Direct `v_valid_ms` calculation when available. |
| `sensor_phy_type` or catalog `phy_type` | CPHY/DPHY correction formula selection. |

Display/panel metadata should provide sink constraints:

| Field | Purpose |
| --- | --- |
| `display_size` | Sink layout/size context. |
| `refresh_rates` | Sink frame period and scanout timing fallback. |
| `format` or supported bitdepth/HDR metadata | Display output interpretation. |

Missing external metadata is normally a warning, not a compute simulation block.

## Judgement Contract (`pipeline.judgement`)

A scenario may declare what the Timing Budget judges. Without the block the name rules apply unchanged
(stage: sensor-synchronous → RT, `mfc|mfd|apv|dpu|panel|display` → Output, `gdc` → Post, else NRT;
sinks: first DPU = preview, first MFC / APV = video, other displays / encoders = extra streams).

```yaml
pipeline:
  judgement:
    sinks:                 # outputs whose interval is judged at the variant fps
    - {node: dpu, kind: preview, label: display}
    - {node: mfc_dec, kind: video, label: decode}
    stages:                # node role -> rt | nrt | post | output (before the name rule)
      decoder: output
    kpis: [interval, latency]   # also: underrun, frame_pacing, start_time (declared, not modeled yet)
```

| Field | Rule |
| --- | --- |
| `sinks[]` | `node` must be a pipeline node; `kind` is `preview` or `video`. The first of each kind is the preview / video interval, the rest are extra streams. A sink inactive in a variant (routing switch, `sim.active: false`) is not judged there; nothing judged and no RT node → `not_applicable`. |
| `stages` | Role → stage, applied before the name rule; Timing Budget `stage_overrides` still win. |
| `kpis` | KPIs without a model are listed in the verdict notes (`판정 계약 KPI 미모델: …`), never counted as passed. |

The evidence generator (`scripts/generate_simulation_evidence.py`) accepts a run on the declared sinks
active in the variant, so screen-off playback is judged on its decoder output.

## Event Jobs (`pipeline.jobs`) — definition only

A one-off or burst piece of work on top of the steady frame DAG (capture shot, camera launch, lens switch, seek)
is declared as a stage DAG. This release validates the definition; the job evaluator comes later, so a declared job
does not change any result yet. Absent = no key in the stored pipeline (the field defaults to `None`).

```yaml
pipeline:
  jobs:
  - id: still_shot
    trigger: {kind: event, at_ms: 200}           # event | burst | periodic
    phases: [precapture, acquire, process, encode]
    buffers: {cap_yuv: {format: YUV420, bitdepth: 10, count: 3}}   # count = pool depth (token capacity)
    stages:
    - {id: aeaf, phase: precapture, kind: fixed, nodes: [n3aa], work: {duration_ms: precapture_ms}}
    - {id: reproc, phase: process, nodes: [byrp, rgbp], frames: zsl_frames, reads: [ZSL_RING_BUF],
       writes: [cap_yuv], chunk: {by: frame}, clock: {CAM: capture_cam_mhz}, after: [aeaf]}
    - {id: merge, phase: process, nodes: [mtnr], frames: zsl_frames, after: [{stage: reproc, per: frame}],
       when: {shooting_mode: [mf, night]}}
    milestones: {thumbnail: merge}
```

| Field | Rule |
| --- | --- |
| `stages[].kind` | `hw` (no work), `domain` (`mcycles` or `mcycles_per_mp`), `sw` (`runtime_ms`), `transfer` (`mb`, `mb_per_s`), `fixed` (`duration_ms`), `sensor` (`mode`; optional `switch_in_ms` / `switch_out_ms`). |
| `stages[].nodes` / `holds` | Pipeline nodes; two or more `nodes` form an OTF group. |
| `after` | Stage ids, or `{stage, per: frame}` for frame-wise pipelining (both stages chunk by frame). The graph must be acyclic. |
| `reads` / `writes` | `reads` names session buffers (`pipeline.buffers`); job buffers flow from the predecessors that `writes` them (or to the stages in a buffer's `to`). Job buffer names must not shadow pipeline buffers. |
| numbers | A number, or an expression of knob parameters (`+ - * /`); string fields take `{param: name}`. Every name must be a `knobs.yaml` param; params / param_rules are exported even without knobs. |
| `when` / `when_node_enabled` | Variant selection, as knob rules. |

## Task Cadence (`node_configs.<node>.timeline`)

The hand-off cadence vocabulary (`sdb.handoff/1`) is also the simulation task model. A node released on
its own cadence runs outside the frame DAG and the frame stages; with `cadence` declared it is judged
against its own deadline.

```yaml
node_configs:
  abox:
    timeline:
      cadence: period      # frame | period | chunk | vsync | divided | event
      period_ms: 10.0      # period / chunk
      duration_ms: 0.6     # when no calculated HW time exists for the node
      # deadline_ms: 10.0  # default: its own period (event: judged only with deadline_ms)
      # phase_ms: 0.0      # first release
```

| `cadence` | Release | Default deadline |
| --- | --- | --- |
| `frame` | with the variant frame (the default; part of the frame DAG) | — (frame stages) |
| `period` | every `period_ms` | `period_ms` |
| `chunk` | every `period_ms` (one chunk: writer flush, network segment) | `period_ms` |
| `vsync` | every 1000 / `refresh_hz` ms (else the panel's selected refresh) | the refresh period |
| `divided` | every `every`-th frame (`every` ≥ 2) | `every` × frame period |
| `event` | once at `phase_ms` | only `deadline_ms` |

- Without `cadence`, a `period_ms` keeps its earlier meaning: an own period outside the frame path, not
  judged. Undeclared tasks give the same results as before.
- The Timing Budget report carries `own_cadence[]` for declared tasks: `node`, `cadence`, `period_ms`,
  `deadline_ms`, `releases`, `worst_response_ms` (end − release, resource waits included),
  `worst_slack_ms` and `ok`. A missed deadline fails the verdict
  (`<node> (<cadence> <period> ms): 응답 … ms > 자체 deadline … ms`).
- Timeline events of own-cadence tasks have `frame_index: null`, `independent_period_ms` (0 for an
  event) and the declared `cadence`.
- A SW task on an own cadence runs on its own thread (`CPU_<node>`) with its own runtime per release
  (the Timing Budget statistic and growth apply). Its Timing Budget CPU power counts
  runtime × frame period / own period (an event releases once: no rate). The evidence CPU energy still
  uses the SW task's `rate_hz`, so keep `rate_hz` = 1000 / period.

## Concurrent Scenarios (`/timing-budget/concurrent`, S-06)

Two to four variants that run at the same time are composed from their own Timing Budget reports
(`sim/concurrency.py`). There is no joint simulation:

- power and BW are summed per component (CPU, HW IP including domain and assumed loads, BW);
- a DVFS domain that several members use runs at the highest set clock any of them needs. Every member IP in
  that domain is re-priced at that level's voltage, `P x (V_shared / V_own)^2` (`shared_domains`, `dvfs_raise_mw`);
- the shared CPU load is the sum of each member's CPU busy time over its own frame period, in core-equivalents.
  A sum above 1 is noted;
- a pipeline node present in several members (one DPU, ABOX or GPU) is listed in `shared_nodes`. Its power is
  the sum of the members' loads, which is an upper bound when one instance serves both;
- the verdict is `fail` when any member fails.

`limits` lists what the composition does not model: contention between members (the same CPU thread or core,
BW latency), a shared domain load re-priced on its combined work, and a timing re-run at the shared clocks.
Each member uses its own project basis and DVFS table, as `/timing-budget/variant` does.

## CPU OPP (`cpu_opp`, S-05)

SW task runtimes are declared at the CPU model's frequency (`cpu.freq_mhz`, the reference). A variant with
`design_conditions.cpu_opp_mhz` runs its CPU SW tasks (`hw_name` CPU) at that OPP (`sim/cpu_opp.py`):

```
runtime(f) = runtime_ref x ((1 - mem_bound) x f_ref / f + mem_bound)
CPU power  = coeff x f x V(f)^2 x busy(f) / period
```

- `mem_bound` is the share of the runtime that does not follow the clock. It is the task's `sw_timing.mem_bound`,
  else `design_conditions.cpu_mem_bound`, else 0.3 (assumed).
- `V(f)` is `design_conditions.cpu_opp_mv`, else the assumed OPP table: the E2600 MID cluster sample, 400 / 1000 /
  1600 / 2000 MHz at 600 / 650 / 720 / 800 mV. An OPP above the table is refused.
- GPU and DSP tasks timed by `sw_timing` keep their runtime. The profile CPU model refuses an OPP, because it
  replays measured clocks.
- The report carries `cpu_opp`: `mhz`, `mv`, `ref_mhz`, and each task's `mem_bound` and `factor`.
  `power.cpu_model` shows the OPP.
- The exploration lever `cpu_opp` (value in MHz) sets the condition, so the CPU clock becomes an axis next to the
  IP levers. A lower OPP costs less per cycle, but it stretches the SW into the NRT / Post budget and the SW growth
  tolerance.
- Opt-in: without `cpu_opp_mhz` the result is unchanged (listed under `OPT_IN`).

## Assumed IP (`ip_param`, S-08)

An architecture question is often "what if this IP were different": a 2x ppc ISP, a single-core encoder, a
higher max clock. These are assumptions, not catalog facts, so they live on the variant node, not in the
shared IP catalog. Catalog rows and other projects stay untouched.

| Field | Effect |
|---|---|
| `node_configs.<node>.sim.ip_params.ppc` / `unit_power_mw_mp` | overrides the catalog value for this node (merged after mode / role) |
| `node_configs.<node>.sim.ip_params.max_clock_mhz` | lowers the catalog cap (never raises it) |
| `node_configs.<node>.sim.ip_params.assume_max_clock_mhz` | replaces the catalog cap and may raise it (assumed IP) |
| `node_configs.<node>.sim.cores` | parallel cores (integer 1..8); required clock / power follow the cores |
| `capabilities.sim.multi_core: {cores, min_pixels}` | catalog declaration of cores; follows `mfc_dual` (on = cores, off = 1, auto = cores from `min_pixels` up) |

- **Precedence for cores:** a node's `sim.cores`, then the catalog `multi_core`, then the built-in rule (a UHD+
  output encoder, not APV, runs on 2 cores). Undeclared data gives identical results
  (`check_engine_equivalence`: 0 differences). The E2600 MFC catalog keeps the built-in rule on purpose:
  Exynos2700 inherits that IP.
- **What-if / exploration:** the `ip_param` change kind (`node_id` + `param` ∈ `ppc`, `unit_power_mw_mp`,
  `assume_max_clock_mhz`, `cores`) writes these fields on a detached copy, and it is an explorable lever. A
  run can sweep, for example, `ppc` 4 / 8 against `cores` 1 / 2, with a `neutral` IQ class.

## Readiness Severity

| Condition | SoC fixture contract | Scenario readiness |
| --- | --- | --- |
| SoC references missing IP catalog | Error | Error if graph uses it |
| Active compute workload has `ppc=0` | Error if no positive ppc exists in IP sim metadata | Blocked |
| Compute IP has no `capabilities.sim` | Borrowable | Blocked only if active and not overridden |
| `unit_power_mw_mp=0` | Warning or borrowable | Warning; power is under-estimated |
| Missing `dvfs_group` | Warning | Warning, unless no fallback and DVFS result is required |
| Missing `vdd` | Warning | Warning; VDD alignment incomplete |
| Sensor/panel missing power/ppc | Not required | Not required |
| Sensor mode lacks pclk/line length | Warning | Warning; v-valid timing may fall back |

## Borrowed Mapping Policy

Early architecture exploration may borrow simulation parameters from a previous
project. Borrowed values must be explicit and traceable:

- source project or SoC
- source IP/ref role
- target exploration role
- scale factor
- confidence or status such as `borrowed`, `estimated`, or `confirmed`

Borrowed values should never be silently merged as if they were measured native
SoC data. Simulation result/debug trace should expose the source.

## Validator

Use the fixture validator before adding or changing a SoC package:

```powershell
uv run python scripts\check_soc_sim_contract.py db_Exynos2600_SM-S947B --soc-id soc-exynos2600
uv run python scripts\check_soc_sim_contract.py demo\generated\scenariodb --soc-id soc-exynos2500
```

Use `--json` for CI or review artifacts.

The validator returns:

- `blocked` when contract errors exist.
- `warning` when only warnings or borrowable items exist.
- `ready` when no issues are found.

The current expected state is that production-like fixtures may still report
warnings for incomplete external timing or borrowable draft IP metadata. Those
warnings are acceptable during exploration but must be reviewed before treating a
result as final project evidence.


## Power Model Parameters (`power_model_params`)

The power *model code* lives in `sim/power_model.py` (IP) and `sim/bw_power.py`
(memory); the *coefficients* are SoC-scoped data. Everything is opt-in: with no
`power_params_ref` the engine uses the code constants and results are unchanged.

```yaml
kind: power_model_params        # 00_hw, id prefix pmp-
id: pmp-exynos2700-v1
soc_ref: soc-exynos2700
ip_model: v1-vfps               # must equal the run's power_model
ref_voltage_mv: 710.0           # unit_power_mw_mp reference point (code default 710 / 30)
ref_fps: 30.0
bw_model: linear-per-gbps       # legacy-coeff | linear-per-gbps
bw: {mw_per_gbps: 50.0, llc_hit_scale: 1.0}
cpu: {clusters: [4 x {name, coeff_uw_per_mhz_v2}], default_cluster: 1, freq_mhz: 2000, volt_v: 0.8}
calibration: {source_evidence: [meas-...], factor_by_ip: {}}   # lineage only, not applied yet
```

- Every field except identity is optional; an absent field keeps the code constant.
- A run selects params with `config.power_params_ref` (`id` or `id@version`, also
  pinnable in `sim.config_profile.run_config`). The service resolves it into
  `config.power_params`, so the request hash covers the coefficients. A params
  document of another SoC is rejected.
- Evidence records `power_breakdown.model.params_ref`, `params_hash` (content
  hash of the coefficients), `calibration_evidence`, `ref_voltage_mv`, `ref_fps`
  (and `bw_model`). Timing-budget CPU power takes its cluster coefficients from
  the params unless `options.cpu` is set explicitly; `cpu_model.source` names them.
- The readiness report adds an advisory `MISSING_POWER_MODEL_PARAMS` warning for a
  SoC without params (it does not change the readiness status).

### BW power models

`bw_power_model` (config / params `bw_model`) selects a `BwPowerModel` from
`BW_POWER_MODELS`; `None` keeps `PowerModel.memory_transfer_power_mw`.

| Model | Formula | Notes |
| --- | --- | --- |
| `legacy-coeff` | `bw_mbs * bw_power_coeff / 1000 * llc_weight` | bit-exact with the built-in path |
| `linear-per-gbps` | `(bw_mbs / 1000) * mw_per_gbps * llc_factor` | "N mW per GB/s" rule of thumb (1 GB/s = 1000 MB/s); default 50; `llc_factor = llc_weight` when `llc_hit_scale` is 1 |

Coefficient precedence: `bw_power_mw_per_gbps` (config) > `params.bw.mw_per_gbps` >
50. `aggregate_power_mw(ports, context)` folds per-port power into the memory-rail
total (default: sum) and is the hook for a later MIF-level / residual model.

## SW-task CPU Power

The simulation total can carry SW-task CPU power (`sim/cpu_power.py`, model `em-v1`),
the same Linux EM formula the timing budget uses:

- `P_task = coeff[uW/MHz/V^2] x f[MHz] x V^2 x util / 1000`, `util = active_ms / period_ms`.
- `active_ms = (sw_timing[<sw_timing_case>]_ms - included HW time) x count_per_frame x cpu_active_ratio`.
  Included HW time is the simulated `hw_time_ms` of `includes_hw_nodes` (e.g. LME inside
  pre_me_rta). `count_per_frame` applies to `sample_unit: invocation`. `cpu_active_ratio`
  (new optional sw_timing field, default 1) marks wall time that is not CPU work
  (storage I/O completion, waits).
- Cluster: sw_timing `cluster` (params cluster name or index); an unknown label (raw
  perfetto CPU list) falls back to the default cluster with a warning.
- Switch: `config.include_cpu_power` — `None` (default) = on only when the resolved
  `power_model_params` carry a `cpu` block, `true` = on with profiler defaults, `false` = off.
  With it off, totals, evidence shape and `params_hash` are unchanged (legacy runs and the
  committed 03_evidence stay valid).
- Output: `SimRunResult.cpu_power_mw` / `cpu_breakdown` (per task: wall, included HW,
  active, cluster, util, mW), `kpi.cpu_power_mw`, `power_breakdown.cpu` (`total_mw`,
  `by_cluster`, `by_task`, `model`), `vdd_power["CPU_<CLUSTER>"]`, and
  `total_power_mw = IP + memory + CPU`.
- Enable per project without touching scenario data: `sim.config_profile.run_config.include_cpu_power: true`
  or a `cpu` block in that SoC's `power_model_params`.

### CPU topology and measured profile

- `power_model_params.cpu` is the SoC's CPU topology: any number of clusters
  (`name`, `core_type`, `cores`, `cpus`, `opps[{mhz, mv, mw_per_core}]` or
  `coeff_uw_per_mhz_v2`, `leakage`, `rail`) plus `dsu`. No fixed cluster count.
- `config.cpu_profile_ref` (measurement evidence) → `config.cpu_profile`: per-frame
  cycles/instructions/stall/bus bytes per task × cluster, cluster frequency residency and
  clock/power-gating ratios (import: `docs/guides/measurement/cpu-profile-import-ko.md`).
  With a profile, CPU power follows the measured placement:
  `P_task = cycles × Σ_l r_l × P_core(f_l)/f_l / period`; cluster static
  `cores × Σ_l r_l leak(V_l) × (1 − power_gated_ratio)`; DSU
  `Σ_l r_l P_dsu(f_l) × active_ratio + leak`. Unattributed cycles are `(other)`.
- `power_breakdown.cpu`: `source` (`sw_timing` | `pmu_profile`), `by_cluster` (incl. DSU;
  joins measured `power.cluster`), `by_task`, `clusters`, `dsu`, `profile_ref`.

## IP Set-clock Term (`power_model: v2-vf`)

`v2-vf` = v1 x `[(1 - a) + a x f_set / f_ref]`.

- `f_ref` (`dvfs_breakdown[].clock_ref_mhz`): the clock the IP physically needs —
  max(work clock, `mipi_ingress`, `vvalid_stream`, `stage_budget`). Work clock =
  `pixels x fps / ppc` (busy the whole period, no SW-margin reserve), so `busy = f_ref / f_set`
  is the IP's real activity (HW time / period). The sensor v-valid exception is a need, not waste.
- Clock above `f_ref` — the SW-margin reserve, OTF / DVFS-group alignment, DVFS level
  quantisation, manual / configured / measured overrides — is charged:
  `dvfs_breakdown[].clock_overhead_mw`, `power_breakdown.ip.clock_overhead_mw`. The SW margin
  changes IP power only through the set clock and voltage it selects (v2-vf 1.2; before, `f_ref`
  carried the margin, so a larger margin read as more busy and lowered power at the same clock).
- `a`: per IP/mode `capabilities.sim[.modes.<mode>].clock_power_fraction`, else
  `power_model_params.ip_clock_power_fraction`, else 0. With `a = 0` v2 equals v1 exactly.
  `dvfs_breakdown[].clock_power_fraction` is the value applied (None under v1).
- Select with `config.power_model: v2-vf` and, for params, `ip_model: v2-vf`.
- Architecture exploration re-scales DVFS headroom analytically with the same factor
  (V^2 x clock factor), so faster levels also pay the clock term.

### Gating-aware IP power and DVFS policy

- v2-vf (1.2): `P = P_v1 x [(1 - a) + a x r x (busy + idle x (1 - cg))] + leak(V) x (1 - pg x idle)`,
  `r = f_set / f_ref`, `busy = min(1, 1/r)`. Per IP/mode catalog sim keys:
  `clock_gating_eff` (cg), `power_gating_eff` (pg), `leakage_mw` (static at ref_V,
  x (V/ref_V)^2.5). Unset = 0 (previous v2; v1 ignores them). This compares "run fast and
  gate" with "lowest clock that fits" in one formula.
- `dvfs_breakdown[]`: `leakage_power_mw`, `clock_overhead_mw` (clock above the need after
  gating), so `total = work + leakage + clock overhead`.
- `config.dvfs_policy`: `min_level` (default) or `same_voltage_up` — per DVFS group, move to
  the fastest higher level with the **same voltage** when the group power rises by at most
  `dvfs_promote_tolerance_pct` (default 0). Under v1 this is free margin; under v2 it depends
  on gating. Skipped for `dvfs_overrides` groups and configured/measured substitutions.
  Recorded as `dvfs_promotion` and a `dvfs_policy` clock-ledger constraint.
- Architecture exploration's analytic DVFS headroom uses the same dynamic/leakage split.

### Memory (BW) power: `mif-linear`

- `bw_model: mif-linear` — `P_mem = base(MIF level) + e_rd x RD + e_wr x WR` (GB/s, LLC-adjusted
  per port). MIF level = max(`qos_lock_mhz_by_dvfs_sn[variant dvfs_sn]`, lowest `mif_opps`
  level with `capacity_mbs x governor_util >= DRAM traffic + other_masters_mbs`).
- DRAM traffic includes CPU BW when a CPU profile is used (`cpu.<cluster>` ports).
- `power_breakdown.memory.mif` records level, reason, traffic, utilization, base and
  other-master power. Coefficients are fitted by `python -m scenario_db.sim.bw_fit`
  (`docs/guides/measurement/bw-model-fit-ko.md`) and carry `bw.fit` lineage.

## Clock Ledger

Each resolved IP (`dvfs_breakdown[].clock_ledger`) keeps every clock tier side by side:

| Field | Meaning |
| --- | --- |
| `throughput_required_mhz` | pixels x fps / ppc / (1 - margin) |
| `constraints[]` | all lower bounds: `mipi_ingress`, `vvalid_stream`, `otf_align`, `stage_budget`, `manual` (`manual_clock_mhz`), `dvfs_group_align`; each `{kind, mhz, reason, source}` |
| `calculated_required_mhz` / `calculated_mhz` | max of the above / DVFS-snapped set clock |
| `configured_*` | BSP/DT/kernel clock with mandatory `reason_code` (`overflow_guard`, `vvalid`, `bsp_default`, `dvfs_scenario`, `qos_lock`, `thermal`, `other`), note, `configured_source` (`project` / `dvfs_scenario` / `variant`) |
| `measured_*` | PMU clock (`weighted_mean`, `dominant`, ...) with `evidence_ref`; `measured_residency` (`{MHz: share}`) and `measured_voltage_basis` (`level` / `residency_weighted` / `snapped_mean`) |
| `basis` / `basis_used` / `fallback` | requested tier / tier that drove this IP / why it fell back |
| `gap` | `configured_minus_calculated_mhz`, `measured_minus_configured_mhz`, `measured_minus_calculated_mhz`, `*_pct`, `calculated_over_throughput_pct`, `cause` |

- `config.clock_basis` (`calculated` default | `configured` | `measured`) picks the tier
  that sets the clock. The chosen clock replaces the calculated requirement, then
  shared DVFS-group / voltage alignment applies as before. A missing value falls back
  to the calculated clock and adds a warning; a configured/measured clock below the
  calculated requirement also warns (it is not marked infeasible).
- `config.configured_clocks` (`{node_id | hw_name | ip_ref: {mhz, reason_code, note, owner, ticket}}`)
  is declared per project in `sim.config_profile.run_config`; the reason code is
  validated at ETL. `config.measured_clock_ref` names a measurement evidence whose
  `clock.ip` observations become the measured tier (`measured_clock_stat`:
  `weighted_mean` | `dominant` | `max`); it must belong to the same scenario/variant.
- Configured clocks are resolved per variant by the adapter, lowest to highest
  precedence: project `configured_clocks` < `configured_clocks_by_dvfs_sn[<variant
  design_conditions.dvfs_sn>]` < `node_configs.<node>.sim.configured_clock`. A
  `configured_clocks_by_dvfs_sn` map without an entry for the variant's `dvfs_sn` warns.
- Tier keys match in this order: `node_id`, `<ip_ref>#<instance_index>`, `ip_ref`,
  `hw_name`, DVFS group (e.g. `CAM`, a whole shared-clock domain). `ip_ref` / `hw_name`
  are skipped (with a warning) when they name several physical instances (same
  ip_ref, different `instance_index`); nodes sharing ip_ref *and* instance_index are one
  time-shared block (e.g. `gdc_m` / `gdc_o`) and share the value.
- Measured weighted-mean clocks are not operating points. With `clock.ip_residency`
  observations the IP (and its DVFS group) resolves at the dominant level, then
  `set_clock_mhz` = residency-weighted mean and voltage `V_eff = sqrt(sum r_i V_i^2)`
  over the visited levels (exact for the V^2 IP model). Without residency a mean is
  snapped up to a level, marked `snapped_mean` and warned (over-estimates power); use
  `measured_clock_stat: dominant` or import residency.
  Explicit DVFS overrides take precedence over residency. If an unblended peer
  in the shared domain needs a higher clock, the resolved domain operating point
  is preserved with a warning. Every visited residency level must fit the IP and
  DVFS table limits; an unsupported level makes the result infeasible even when
  the dominant level is supported. Residency frequencies and shares must be finite.
- The ledger is informational at the default basis: clock, voltage, power and
  `params_hash` are identical to a run without it. Power changes with the clock only
  through the DVFS voltage of the selected level, so a DVFS table is required for a
  basis comparison to show a power difference.
- Comparisons: the prediction side of `clock.ip` is `clock_ledger.calculated_mhz`
  (never a substituted clock), per `<ip_ref>#<instance>` and also bare `ip_ref` when it
  names one instance. `compare_prediction_measurement` returns `model_lineage`
  (power/BW model, params ref/hash, clock basis) with warnings
  (`CLOCK_BASIS_SUBSTITUTED`, `CIRCULAR_MEASURED_CLOCK`, `CODE_CONSTANT_COEFFICIENTS`).
  Predictions store `metrics.model_lineage`; prediction compare / board report
  `lineage_changes` when the model, coefficients or clock basis changed.
- Reports: `ip_detail_rows` gains `Calc/Cfg/Meas Clk` + `Clk Gap`, and the HTML report a
  "Clock Ledger" section, only when a configured/measured tier or non-default basis exists.
