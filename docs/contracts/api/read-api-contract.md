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
| `GET /api/v1/scenarios/{scenario_id}/variants/{variant_id}/view?level=2&expand={alias-or-node}` | Semantic module detail view. `expand` accepts `camera`, `video`, `display`, an active pipeline node id, or an IP catalog id. The projection renders only declared module data from the active graph and IP catalog. |

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
- `data.module_ref`
- `data.module_kind`
- `data.module_direction`
- `data.module_status`
- `data.port_ref`
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

## Simulation Timing Overlay

When a matching saved simulation is applied, `metadata.simulation_evidence_id`
identifies the exact evidence used by the view. Consumers should fetch timing
details by this ID instead of resolving `latest` a second time.

Optional timing additions to `nodes[*].data.sim_overlay`:

- `start_ms`, `end_ms`: finite frame-0 schedule bounds; null if unavailable.
- `critical`, `bottleneck`: flags summarized across the evidence's frames.

`edges[*].data.critical` is null for a plain projection. On a simulation overlay,
it is true only for an unambiguously mapped direct predecessor edge in the same
frame with consecutive critical-path ranks and critical flags on both events.
Unrelated critical nodes, cross-frame resource dependencies, risk edges and
legacy events without predecessor/rank metadata do not establish this marker.
Node matching uses exact IDs or a unique explicit projection ID; label substring
matching is not supported.

This contract is covered by `tests/unit/test_view_sim_overlay.py` and
`tests/integration/test_viewer_timing_contract.py`.

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

## Level 2 Module View Contract

Level 2 is a semantic module-detail projection, not a hardcoded reference
diagram. The backend resolves the active variant topology first, then maps the
selected `expand` target to active pipeline nodes:

- `camera` expands active ISP/camera-processing nodes.
- `video` expands active codec nodes such as MFC/APV.
- `display` expands active DPU nodes.
- A concrete pipeline node id or IP catalog id expands that single active node.

The projection renders declared IP-internal modules only:

- Functional blocks come from `capabilities.properties.subblocks` or
  `hierarchy.submodules`.
- DMA/CIN/COUT nodes come from `capabilities.properties.modules`.
- Module-to-module routes come from active scenario pipeline edges and
  `capabilities.properties.internal_edges`.
- Buffer nodes are emitted only for actual pipeline buffer handoffs, with
  format/compression/LLC placement from scenario buffers and variant overrides.

If a selected target has no module-level declaration, the response uses:

- `metadata.layout = "level2-unavailable"`
- `metadata.level2_available = false`
- `metadata.unavailable_reasons[]`
- `metadata.required_data[]`

When some nodes in an alias expansion are renderable and others are not, the
response still returns `metadata.layout = "level2-module-detail"` and records
the skipped nodes in `metadata.omitted_reasons[]`. The Viewer should show those
reasons as data-quality guidance rather than drawing synthetic DMA/SYSMMU nodes.

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

## Query API Contract

`POST /api/v1/query/variants` returns `200 OK` only for valid query requests.
Business validation failures such as unsupported fields or numeric aggregation
on non-numeric fields return `400 bad_request` using the standard error
envelope:

```json
{
  "error": "bad_request",
  "detail": ["Unsupported query field: raw.sql"]
}
```

Aggregation metrics `min`, `avg`, `p50`, `p95`, and `max` require a field with
type `number` in the query field registry. `count` is allowed for any supported
field. Missing aggregation group values are serialized as JSON `null`; the
literal string `"(none)"` remains distinct from a missing value.

Top-level and grouped AND predicates for project ID, SoC, board type, scenario
ID, variant ID, and severity can narrow the SQL scope. Same-field equality OR
groups can also narrow it by unioning their allowed values. Mixed-field ORs,
inherited axes, topology/buffer facts and negative predicates stay in the fact
evaluator. Text identity filters preserve case/space normalization; numeric,
null and empty comparisons are evaluated in Python. A child with missing
severity remains a candidate until its inherited severity is resolved.

Variant/severity scope now constrains the scenario query with EXISTS before
scenario rows and pipelines are materialized. Ancestor reads use exact
(scenario_id, variant_id) pairs. Final predicates, sorting, total and aggregates
still operate on the full filtered candidate set before pagination.

Architecture Query reads historical evidence identity and run_info first, then
loads KPI/context only for the latest simulation per scenario/variant. UTC
parsing, invalid/missing timestamp fallback, ID ties and simulation-only selection
are unchanged. The evidence-row guard still applies to the scanned history,
not just to the number of selected winners.

The evaluator is intentionally bounded. If the SQL-prefiltered scenario,
project, variant, evidence, issue, or facet candidate set exceeds its configured
limit, the API returns `400 bad_request` with
`candidate_limit_exceeded` instead of loading an unbounded working set. Narrow
the request with `scope` or scalar identity predicates. Limits are configured
with `SCENARIO_DB_QUERY_MAX_CANDIDATES`,
`SCENARIO_DB_QUERY_MAX_EVIDENCE_ROWS`, `SCENARIO_DB_QUERY_MAX_ISSUE_ROWS`, and
`SCENARIO_DB_QUERY_FACETS_MAX_CANDIDATES`; all must be positive.

## Navigation catalog summaries

`GET /api/v1/catalog/{kind}` is an additive, paged summary API used by the SPA.
Supported kinds are `soc-platforms`, `projects`, `scenarios`, and `variants`.
The existing resource list/detail endpoints retain their full response shapes.

- Envelope: `items`, `total`, `limit`, `offset`, `has_next`.
- Items: `id`, `name`, `category` (string array), and relevant ownership fields
  `project_ref`, `soc_ref`, `board_type`, `scenario_id`. Absent fields are null.
- Only display/identity expressions are selected in SQL. Pipeline, globals,
  variant overlays and evidence detail are not loaded or serialized. Variant
  catalog entries are identities, not resolved design-condition summaries.
- `limit` defaults to 100 and is capped at 200; `offset` defaults to 0.
- `q` searches ID/name and scenario category, case-insensitively. `%` and `_`
  are literal search characters, not SQL wildcards.
- `id` is an exact selected-item lookup and retains the same ownership filters.
- Project/scenario/variant lists support `soc_ref` and `board_type` through the
  owning project; `project_ref` narrows projects, scenarios or variants.
- Variant lists require `scenario_id`. Missing scope returns 422.
- `sort_by=id|name|category`, `sort_dir=asc|desc`; category is scenario-only.
  Sorting is performed by PostgreSQL before paging, with ID as a stable tie
  breaker. Category sorting follows its stored JSON text representation.
- As with the existing offset API, concurrent additions/removals between page
  requests do not constitute a snapshot. No selection is inferred from a page.

The SPA fetches one page at a time, debounces search by 250ms and cancels stale
requests. A selected ID outside the visible page is resolved separately in the
same scope, so URL restoration does not require downloading earlier pages.

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

## Camera SW timing profiles and history buffers

The IS v15 fixture guide is [Camera Recording](../../../db_fixtures_Exynos2600_S26Plus/README.md).
`node_configs.<node>.sw_timing` accepts `min_ms`, `mean_ms`, `max_ms`,
`start_jitter_mean_ms`, `includes_hw_nodes`, `value_source` (`assumed`, `measured`,
`projected`), and `source_note`. Active simulation profiles require a nonnegative,
ordered min/mean/max interval. `design_conditions.sw_timing_case` selects the
wall-time statistic; the mean start delay remains a release delay in all cases.
Included hardware is collapsed into its enclosing timing stage and is not executed
a second time. An aggregate stage is not a CPU duty-cycle measurement.

Simulation evidence preserves these optional fields in `sw_task_timing` through
persistence and result retrieval. Missing percentiles remain missing. An assumed
SW profile marks the simulation as estimated and limits its resolution result to
`exploration_only`; a passed clock candidate is not a hardware sign-off.

`pipeline.buffers.<id>.history` records `node_id`, negative `frame_offset`,
`read_ports`, `write_ports`, and initialization intent. The current recording model
counts previous-frame DMA in steady state without introducing same-frame DAG
self-cycles. Detailed inter-frame buffer hazards are not simulated. Explicit
multi-plane port pairs split pixel planes, while a shared producer write is counted
once per node/port/buffer even when multiple consumers read it. Viewer size references
resolve arbitrary scenario anchors and variant size overrides, including pyramid layers.


Auxiliary DMA with no modeled consumer can be declared at
`pipeline.buffers.<id>.dma`: `node_id`, `read_ports`/`write_ports`, optional
`enabled` (default true), and optional `activation_flag` naming a boolean in the
node configuration. A buffer override can change `dma.enabled` without replacing
the endpoint's node and port mapping. These endpoints add traffic independently
of graph edges and history. For an uncharacterized buffer, `size_status: unknown`
excludes transfers with an explicit warning and keeps viewer dimensions unknown;
it must not fall back to recording resolution. Set the size reference, format,
bitdepth and size status together when characterization becomes available.
