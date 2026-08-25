# Simulation Integration Plan

## Goal

Run BW, power, performance, and timeline simulation from a resolved
scenario/variant, persist the result as `evidence.simulation`, then expose it
through FastAPI and the Streamlit viewer/dashboard.

## Implementation Steps

1. Core formula engine
   - Port SimEngine formulas into `src/scenario_db/sim`.
   - Keep BW, power, performance, and DVFS code pure Python/Pydantic.
   - Source formulas from the read-only legacy simulator at
     `E:\10_Codes\23_MMIP_Scenario_simulation2`.

2. Timing graph engine
   - Include NetworkX and SimPy in the `sim` dependency group.
   - Use NetworkX for DAG validation, topological ordering, and future critical
     path analysis.
   - Use SimPy for SW-task-inclusive timing simulation so fixed SW tasks,
     HW tasks, and later token/resource contention can produce timeline events.
   - Store the first result shape as `SimulationEvidence.timeline_events`.

3. ScenarioDB adapter
   - Read effective scenario data through `load_canonical_graph()`, not raw YAML.
   - This keeps `derived_from_variant`, `routing_switch`, and `topology_patch`
     behavior consistent with the Read API and viewer.
   - Use `node_configs.*.sim` for per-node port/workload simulation inputs.
   - Use `IpCatalog.capabilities.sim` for IP simulation parameters such as
     `hw_name`, `ppc`, `unit_power_mw_mp`, `vdd`, and `dvfs_group`.
   - Treat sensor modules and display panels as external source/sink parts, not
     SoC compute IP. They should not create PPC/clock/power workloads.

4. Evidence persistence
   - Keep existing `kpi` and `ip_breakdown` fields.
   - Add JSONB detail fields:
     - `dma_breakdown`
     - `timing_breakdown`
     - `dvfs_breakdown`
     - `timeline_events`
     - `vdd_power`
     - `params_hash`

5. API surface
   - Add `/api/v1/simulation/run` for synchronous formula simulation first.
   - Add result lookup endpoints backed by `evidence`.
   - Later, allow the run request to select `mode=formula` or `mode=timeline`.

6. Viewer and dashboard
   - Viewer reads latest simulation evidence as an optional overlay.
   - Evidence Dashboard runs simulation, selects evidence, and visualizes:
     - BW per DMA port
     - power per IP and VDD
     - DVFS decision table
     - HW/SW timeline events

## NetworkX + SimPy Scope

The first NetworkX+SimPy implementation is intentionally small:

- DAG precedence only
- fixed `duration_ms` per task
- deterministic output events:
  `task_id`, `node_id`, `hw_name`, `task_type`, `start_ms`, `end_ms`,
  `duration_ms`, `predecessors`

The current implementation keeps that base shape and adds optional timing
details:

- `frame_index`
- `resource_id`
- `ready_ms`
- `resource_wait_ms`
- `token_wait_ms`
- `critical`
- `critical_path_rank`
- `constraint_type`
- `source_fps`
- `v_valid_ms`
- `refresh_hz`
- `scanout_ms`
- `deadline_ms`
- `slack_ms`

Resource contention, M2M/OTF token transfer delay, multi-frame release timing,
and critical-path marking are modeled without removing existing
`timeline_events` fields. Evidence KPI also records `critical_path_ms` and
`critical_path_task_count`.

## Source/Sink Timing Scope

1. Sensor source timing metadata
   - Keep sensor modules out of SoC power/performance workloads.
   - Read sensor mode metadata such as `sensor_fps`, line length, pixel clock,
     frame length, and calculated `v_valid_ms` when available.
   - Use that metadata as a source timing constraint for CSIS/camera pipeline
     timeline analysis, not as sensor core power or PPC timing.
   - Current implementation injects `constraint_type=source`, `source_fps`,
     `release_period_ms`, and `v_valid_ms` into sensor timeline tasks. If
     `v_valid_ms` is missing, it is calculated from `sensor_size`,
     `sensor_pclk`, and `sensor_line_length_pck` when possible.

2. Display sink timing metadata
   - Keep display panels out of SoC power/performance workloads.
   - Use panel refresh/scanout timing as a sink constraint for DPU/display
     timeline analysis when panel metadata is available.
   - Current implementation injects `constraint_type=sink`, `refresh_hz`,
     `scanout_ms`, `deadline_ms`, and calculated `slack_ms` into display sink
     timeline tasks.

3. Remaining viewer work
   - Render source valid windows, sink deadlines, and slack in the Pipeline
     Viewer overlay.
   - Keep the current `timeline_events` compatibility shape for existing
     viewer overlays.

## Verification

Use the project environment:

```powershell
uv sync --group dev --group sim
uv run --group dev --group sim pytest tests\unit
```
