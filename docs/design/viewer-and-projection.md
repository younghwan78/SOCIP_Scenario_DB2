# Viewer and Projection Architecture

| Field | Value |
| --- | --- |
| Status | Current |
| Last verified | 2026-08-26 |
| Primary code | `src/scenario_db/view`, `api/routers/view.py`, `dashboard/` |
| Primary tests | `tests/unit/view`, `tests/unit/dashboard`, view API integration tests |

## 1. Selection and identity

The viewer selection hierarchy is:

```text
SoC Platform -> Project / Board -> Scenario -> Variant -> View Level
```

`Project` carries board/form-factor metadata such as `board_type`, `board_name`, sensor/display
module references, and default SW profile. Board-aware API filters must be used before adding
dashboard-only filtering.

Scenarios may have no variants. Base scenarios use `/scenarios/{scenario_id}/view`; variant views
use `/scenarios/{scenario_id}/variants/{variant_id}/view`. The service never creates a dummy
variant to satisfy the UI.

## 2. Projection pipeline

Evidence read optimization verified on 2026-09-06: the standard view service
loads only the ten evidence columns needed by projection and rule contexts.
Timeline, calculation trace, rail and other detail blobs are not loaded for every
historical evidence row. An explicitly requested simulation overlay still loads
its selected evidence through the existing detail path.

`load_canonical_graph(..., include_evidence_details=False)` and the corresponding
base loader opt into this projection. Other callers retain the full default.
Deferred columns use SQLAlchemy `raiseload` so a future accidental access fails
instead of silently issuing a per-row query. PostgreSQL regression tests compare
the full and reduced view responses and ensure projection emits no extra SQL.

Architecture Query similarly selects ten evidence columns used by facts and
matching. Latest-evidence selection preserves its timestamp/ID tie policy with a
single pass rather than sorting each group. Candidate limits and matching scope
remain unchanged.

1. The repository builds a `CanonicalScenarioGraph` from PostgreSQL rows.
2. Variant inheritance, routing switches, topology patches, node configs, and buffer overrides
   form the effective graph.
3. `view.service` selects the requested Level/mode projector.
4. The projector produces API-neutral `ViewResponse` nodes, edges, summaries, and metadata.
5. An optional matching simulation evidence row augments the response.
6. Streamlit renders the response with ELK.js/SVG and detail panels.

The view service requires a DB session for real requests; demo/reference projections are not a
silent production fallback.

## 3. Levels

### Level 0

Supported modes are exactly `architecture`, `topology`, and `resource`. Unknown modes fail
validation rather than falling back.

- `architecture`: system layers and active HW/memory/resource relationships.
- `topology`: active scenario nodes, buffers, data/control edges, and SW task flow.
- `resource`: scenario resource overview with sensor/display summaries and simulation metrics.

### Level 1

Level 1 groups active IP detail into a semantic DAG. Memory nodes may be collapsed into effective
edges while explicit hierarchy and DVFS/IP grouping remain visible.

### Level 2

Level 2 is a selectable drill-down for `camera`, `video`, and `display`. It uses semantic fixture
data when present and preserves a reference projection for compatible scenarios.

## 4. Projection invariants

- Disabled variant nodes and edges do not reappear through inferred layout edges.
- Schema-declared resource kinds take priority over token/name heuristics.
- Buffer compression and memory placement remain distinct fields and badges.
- A simulation overlay must belong to the requested scenario and variant.
- View projections are read-only and never write canonical scenario data.
- Variant-matrix pagination does not change the design-axis key set; keys come from the full
  filtered result set.

## 5. Dashboard surfaces

| Page | Responsibility |
| --- | --- |
| DB Explorer | Catalog, scenario, variant, and import-health inspection |
| Pipeline Viewer | Level 0/1/2 graph and simulation overlay |
| Architecture Query | Bounded topology/evidence fact query |
| Evidence Dashboard | Simulation/measurement result and comparison |
| Exploration Workbench | Fixture-backed draft/recipe compilation and candidate comparison |
| Import Workbench | Canonical bundle review and Write API staging |

Dashboard clients should remain thin: contract validation, identity checks, and mutations belong
to backend services rather than Streamlit session state.

## 6. Change checklist

For a view-contract change, update `api/schemas/view.py`, projector code, dashboard client and
renderer, the Read API contract, focused unit tests, and golden JSON where intentionally changed.
Run the dashboard regression checklist after fixture or renderer changes.
