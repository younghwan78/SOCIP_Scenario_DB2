# Pipeline Viewer simulation timing hardening

Status: implementation and validation summary prepared for PR.
Base: main at `ff743cf`. Source feature: `5570061`, reworked to enforce
evidence identity, success-only caching and proven critical dependencies.

## Implemented behavior

- Pipeline Viewer includes a saved simulation picker and a Simulation Timing
  panel. Evidence Dashboard links open the panel with `panel=timing`.
- Latest selection is resolved once. Level 0 resource/topology views, other
  levels and HTML export use the same explicit evidence ID. The timing panel
  reads the actual ID from the displayed view's metadata.
- The detail response is checked against ID, simulation kind, scenario and
  variant before rendering. Base scenarios do not retrieve another variant's
  evidence. Picker keys are isolated by the complete context hash.
- Only successful list, detail and view loads are cached. Failures remain
  visible errors with retry; empty successful results have a separate state.
- Schedule windows use finite frame-0 bounds. Flags may summarize later frames,
  but later times cannot replace the frame-0 window. Exact/unambiguous identity
  matching prevents `isp` data from being applied to `display`.
- Critical edges require consecutive ranked, critical predecessor events in the
  same frame. Endpoint flags alone are insufficient. Risk edges, duplicate task
  identities and cross-frame links are not highlighted.
- ELK displays critical nodes in red, bottlenecks in amber and proven critical
  edges with a red halo while retaining the underlying flow color.

## Verification

- Full Python unit and isolated PostgreSQL integration suite: **1,325 passed**,
  one existing Starlette test-client deprecation warning.
- Ruff passed; configured mypy scope of 16 files passed.
- Streamlit AppTest runs the actual Pipeline Viewer controller with synthetic
  API responses. It verifies one latest request, matching IDs for both Level 0
  views and timing, recovery on rerun, and the explicit timing retry button.
- PostgreSQL/API testing inserts a newer result after rendering a view and
  verifies that timing still loads the original evidence. Foreign variant detail
  requests are rejected before presentation.
- Scheduler-generated events verify the actual ranked path while excluding a
  shortcut edge between otherwise critical nodes. Missing rank/predecessors,
  cross-frame events and ambiguous identities are negative regression cases.
- Chromium rendered a standalone generated ELK view: two critical nodes, one
  bottleneck node and exactly one critical edge halo. The only console error was
  the test HTTP server's missing favicon; no graph JavaScript error was reported.

Runtime logs and the visual check image are under ignored `output/` paths and
are not source artifacts.

## Deliberate limits

Legacy evidence without ranked dependency metadata still shows its timeline and
node flags, but cannot prove a red edge. Implicit routes through collapsed or
buffer-only projection nodes are not guessed. The picker lists the 50 newest
runs and accepts an older ID manually. The existing Workbench renderer and
prediction/measurement baseline workflow are retained.
