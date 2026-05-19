# Read API Contract

This document freezes the current read-side contract before Write API work starts.

## Scope

Read API covers these public read paths:

- Definition: projects, scenarios, variants, matched issues.
- Capability: SoC platforms, IP catalog, SW profiles, SW components.
- Evidence: evidence list/detail/summary and compare endpoints.
- Decision: reviews, issues, waivers, gate rules.
- Runtime: canonical graph, resolver result, review gate result.
- View: Level 0/1/2 viewer projections.

Variant read paths return resolved variant overlays. If a variant has
`derived_from_variant`, the API merges the parent chain before returning the
variant, running resolver/review gate, or building viewer projections.

Write/admin endpoints remain out of scope for the current phase.

## Runtime And Viewer Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/scenarios/{scenario_id}/variants/{variant_id}/graph` | Canonical graph summary for a scenario variant. |
| `GET /api/v1/scenarios/{scenario_id}/variants/{variant_id}/resolve` | Resolver result against HW/SW capability data. |
| `GET /api/v1/scenarios/{scenario_id}/variants/{variant_id}/gate` | Review gate status, matched rules, issue/waiver result. |
| `GET /api/v1/scenarios/{scenario_id}/variants/{variant_id}/view?level=0&mode=resource` | Level 0 Scenario Resource Overview payload for resource rows, buffers, endpoints, and subsystem metrics. |
| `GET /api/v1/scenarios/{scenario_id}/variants/{variant_id}/view?level=0&mode=topology` | Level 0 active topology graph with scenario nodes and explicit buffer handoff nodes. |
| `GET /api/v1/scenarios/{scenario_id}/variants/{variant_id}/view?level=0&mode=architecture` | Legacy Level 0 App/Framework/HAL/Kernel/HW/Memory architecture overview. |
| `GET /api/v1/scenarios/{scenario_id}/variants/{variant_id}/view?level=1` | Semantic IP detail DAG grouped by hierarchy group and IP block. |
| `GET /api/v1/scenarios/{scenario_id}/variants/{variant_id}/view?level=2&expand=camera` | Camera drill-down with submodule, DMA, SYSMMU, and buffer context. |
| `GET /api/v1/scenarios/{scenario_id}/variants/{variant_id}/view?level=2&expand=video` | Video encode drill-down. |
| `GET /api/v1/scenarios/{scenario_id}/variants/{variant_id}/view?level=2&expand=display` | Display output drill-down. |

## Variant Resolution Contract

`GET /api/v1/scenarios/{scenario_id}/variants/{variant_id}` and list endpoints
return the effective variant configuration:

- Parent values are applied first.
- Child dict fields deep-merge over the parent.
- `design_conditions_override` is applied on top of inherited `design_conditions`.
- `routing_switch` and `topology_patch` list fields are appended without duplicates.
- `tags` are appended without duplicates.
- `resolved=true` and `inheritance_chain` identify that the response is a read projection.

The canonical DB rows remain authored data. Resolution is a deterministic read
projection used by Read API, resolver, review gate, and viewer projection.

Effective topology is also resolved at read time:

- `routing_switch.disabled_nodes` removes nodes and all touching edges.
- `routing_switch.disabled_edges` removes matching base edges.
- `topology_patch.remove_edges` removes matching base edges.
- `topology_patch.add_nodes` injects validated SW task nodes.
- `topology_patch.add_edges` injects validated SW task edges.
- Viewer projections use this effective topology when an overlay is present.

## ViewResponse Required Shape

The viewer depends on these top-level fields:

- `level`
- `mode`
- `scenario_id`
- `variant_id`
- `summary`
- `nodes`
- `edges`
- `risks`
- `metadata`
- `overlays_available`
- `level0_resource_overview` when `level=0`

Each node must include:

- `data.id`
- `data.label`
- `data.type`
- `data.layer`
- `position`

Viewer-critical optional node fields:

- `data.summary_badges`
- `data.capability_badges`
- `data.hierarchy_group`
- `data.ip_group`
- `data.dvfs_group`
- `data.role_hw_name`
- `data.semantic_source`
- `data.active_operations`
- `data.memory`
- `data.placement`
- `data.dma_count`
- `data.shared_resource`
- `data.matched_issues`
- `data.detail_items`
- `data.warning`
- `data.view_hints`

Each edge must include:

- `data.id`
- `data.source`
- `data.target`
- `data.flow_type`

Viewer-critical optional edge fields:

- `data.latency_class`
- `data.buffer_ref`
- `data.memory`
- `data.placement`
- `data.label`
- `data.detail_items`

`detail_items` is a pre-rendered list of concise strings for Viewer tooltips and
right-side inspectors. It should expose the resolved variant context that is hard
to infer from graph shape alone:

- `node_configs`: selected mode, input/output ports, format, bitdepth, SW task processor, and duration.
- `buffer_overrides`: per-variant format, bitdepth, compression, alignment, and buffer size.
- `memory placement`: LLC allocation policy, allocation size, owner, and expected BW reduction when available.

The response `metadata.variant_overlay` summarizes the resolved overlay used by
the projection:

- `resolved`
- `inheritance_chain`
- `disabled_nodes`
- `disabled_edge_count`
- `topology_patch.add_nodes/add_edges/remove_edges`
- `node_config_count`
- `buffer_override_count`
- `sw_task_count`

## Level 0 V2 View Contract

Level 0 is split into two normal consumer modes:

- `mode=resource` returns the Scenario Resource Overview. `nodes` and `edges`
  are intentionally empty, while `level0_resource_overview` carries the table,
  buffer handoff list, sensor endpoint details, display composition details,
  and subsystem metric breakdown.
- `mode=topology` returns the active scenario topology. It uses the effective
  resolved graph, emits one `ip-*` node for each active pipeline node, emits
  one `buf-*` node for each active buffered handoff, and splits buffered edges
  into `producer -> buffer -> consumer`. The dashboard renders this as
  `Level 0 - Topology Overview`.

`mode=architecture` remains available as a legacy compatibility projection, but
the Pipeline Viewer uses `resource` plus `topology` for Level 0.

`level0_resource_overview.rows[]` includes:

- `sequence_index`
- `node_id`
- `label`
- `resource_domain`
- `resource_kind`
- `subsystem`
- `role`
- `input`
- `output`
- `flow`
- `buffer_refs`
- `badges`
- `metrics`
- `detail_items`

`level0_resource_overview.sensors[]` describes active sensor endpoints and
selected modes. `level0_resource_overview.displays[]` describes DPU composition,
panel mode, and display layers when those fields are available from the
scenario/variant.

## Memory Contract

Memory descriptor and memory placement are separate concepts.

`memory` describes the buffer:

- `format`
- `bitdepth`
- `planes`
- `width`
- `height`
- `fps`
- `stride_bytes`
- `size_bytes`
- `alignment`
- `compression`

`placement` describes where/how the buffer is placed:

- `llc_allocated`
- `llc_allocation_mb`
- `llc_policy`
- `allocation_owner`
- `expected_bw_reduction_gbps`

Compression must not be used as a proxy for LLC placement.

## Error Contract

All handled API errors should return:

```json
{
  "error": "not_found",
  "detail": "Scenario not found: uc-missing"
}
```

Current error codes:

| HTTP | `error` |
| --- | --- |
| 400 | `bad_request` |
| 404 | `not_found` |
| 409 | `conflict` |
| 422 | `validation_error` |
| 501 | `not_implemented` |

FastAPI request validation errors also use `validation_error` with a list in `detail`.

## Regression Tests

The read contract is guarded by:

- `tests/unit/api/test_smoke.py`
- `tests/unit/api/test_pagination.py`
- `tests/integration/test_runtime_view_e2e.py`
- `tests/integration/test_api_definition.py`
- `tests/integration/test_api_capability.py`
- `tests/integration/test_api_evidence.py`
- `tests/integration/test_api_decision.py`

Run unit tests:

```powershell
uv run --group dev pytest tests\unit
```

Run read/view integration tests:

```powershell
uv run --group dev pytest tests\integration\test_runtime_view_e2e.py
```
