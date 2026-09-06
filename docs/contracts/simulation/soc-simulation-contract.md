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
uv run python scripts\check_soc_sim_contract.py db_fixtures_Exynos2600_S26Plus --soc-id soc-exynos2600
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
