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

## IP Set-clock Term (`power_model: v2-vf`)

`v2-vf` = v1 x `[(1 - a) + a x f_set / f_ref]`.

- `f_ref` (`dvfs_breakdown[].clock_ref_mhz`): the clock the IP physically needs —
  max(throughput, `mipi_ingress`, `vvalid_stream`, `stage_budget`). The sensor v-valid
  exception is a need, not waste.
- Clock above `f_ref` — OTF / DVFS-group alignment, DVFS level quantisation, manual /
  configured / measured overrides — is charged: `dvfs_breakdown[].clock_overhead_mw`,
  `power_breakdown.ip.clock_overhead_mw`.
- `a`: per IP/mode `capabilities.sim[.modes.<mode>].clock_power_fraction`, else
  `power_model_params.ip_clock_power_fraction`, else 0. With `a = 0` v2 equals v1 exactly.
  `dvfs_breakdown[].clock_power_fraction` is the value applied (None under v1).
- Select with `config.power_model: v2-vf` and, for params, `ip_model: v2-vf`.
- Architecture exploration re-scales DVFS headroom analytically with the same factor
  (V^2 x clock factor), so faster levels also pay the clock term.

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
