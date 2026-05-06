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

This is enough to save SW-task-inclusive timing evidence in DB. Resource
contention, M2M/OTF token queues, join policies, and multi-frame behavior can be
added later without changing the persisted `timeline_events` shape.

## Verification

Use the project environment:

```powershell
uv sync --group dev --group sim
uv run --group dev --group sim pytest tests\unit
```

