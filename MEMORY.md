# Project Memory

This file records repo-local implementation decisions and current state. It is not the Codex internal memory store.

## 2026-04-26 Viewer Direction

- The viewer moved from Cytoscape-style rendering toward ELK.js/SVG because SoC block diagrams need readable orthogonal routing, hierarchy groups, and professional topology/detail diagrams.
- The legacy reference project `E:\10_Codes\23_MMIP_Scenario_simulation2` remains read-only and is used as the visual behavior reference.
- The current renderer lives in `dashboard/components/elk_viewer.py`.
- The FastAPI view projection still returns `ViewResponse`; the Streamlit renderer adapts that response into an ELK graph.

## Current Viewer Behavior

- Level 0 shows architecture overview and SW task topology on one vertically scrollable page.
- Level 0 architecture should include `App`, `Framework`, `HAL`, `Kernel`, `HW`, and `Memory`.
- Memory is treated as first-class review context and should appear below HW in the overview.
- Topology, Level 1, and Level 2 should stay close to the legacy ELK visual style.
- Edges should be orthogonal and should not be hidden behind group/layer backgrounds.
- HW-to-HW summary edges are kept at Level 0 even when buffer-specific edges are also shown.

## Fixture Decisions

- Demo data is loaded from `demo/fixtures`.
- The main demo scenario is `uc-camera-recording` with variant `UHD60-HDR10-H265`.
- Fixture view data is stored under `pipeline` as JSON-compatible YAML:
  - `buffers`
  - `architecture_graph`
  - `task_graph`
  - `level1_graph`
- Buffer data should include format, bitdepth, planes, size reference, alignment, compression, and memory placement.
- LLC placement must remain separate from compression.

## Commands

Run API:

```powershell
uv run uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
```

Run viewer:

```powershell
$env:SCENARIODB_API_BASE="http://127.0.0.1:18000/api/v1"
uv run --group dashboard streamlit run dashboard\Home.py --server.port 18502 --server.address 127.0.0.1
```

Run unit tests:

```powershell
uv run --group dev pytest tests\unit
```

## Recent Local Commits

- `71c6a42 Add ELK viewer rendering`
- `de327fc Align viewer fixture with legacy ELK layout`
- `d879b9c Document viewer runbook and test workflow`

## 2026-04-26 Read API Wrap-Up

- Read API is considered ready to freeze for the current viewer/demo milestone.
- The read-side contract is documented in `docs/read-api-contract.md`.
- Error responses are normalized as `{ "error": "...", "detail": ... }` for handled `HTTPException`, `NoResultFound`, `IntegrityError`, and request validation errors.
- Runtime/view contract tests are concentrated in `tests/integration/test_runtime_view_e2e.py`.
- Before changing Read API response shape, update the contract document and tests first.

## 2026-05-01 Import And Board-Aware Viewer Selection

- Import Workbench now builds `scenario.import_bundle` payloads from generated canonical YAML, stages them through Write API, validates, previews semantic diff, and applies through canonical upsert mappers.
- Import diff should classify documents by canonical content, not by legacy YAML file hash alone. Identical imported documents should appear as `unchanged`; changed same-ID documents should appear as `modified`.
- Diff Preview in the Workbench should show flat columns: `field`, `change`, `existing_count`, `import_count`, `added`, `modified`, `unchanged`, and `removed`.
- After apply, Import Workbench should offer `Open in Viewer` links with `soc_id`, `project_id`, `scenario_id`, and `variant_id` query parameters.
- Viewer selection hierarchy is now `SoC Platform -> Project / Board -> Scenario -> Variant -> View Level`.
- `Project` is the board/form-factor boundary under the same SoC. Use project metadata for `board_type`, `board_name`, `sensor_module_ref`, `display_module_ref`, and `default_sw_profile_ref`.
- Example board types under the same SoC include `ERD`, `SEP1`, and `SEP2`.
- Scenarios may have no variants. Viewer should use base scenario view endpoint `/api/v1/scenarios/{scenario_id}/view` rather than forcing a dummy variant.
- Board-aware Read API filters are available on `/projects`, `/scenarios`, and `/variants`.

## 2026-05-12 Simulation Refactoring And Debug Trace Wrap-Up

- Current pushed GitHub head is `a3d9539 Add detailed simulation formula trace tables`.
- API entrypoint is `scenario_db.api.app:app`; previous `scenario_db.api.main` is not valid.
- Standard local ports remain FastAPI `127.0.0.1:18000` and Streamlit `127.0.0.1:18502`.
- Latest local verification after the refactoring/debug-trace work was `uv run pytest tests/unit -q` with `408 passed`.
- Evidence Dashboard result rendering has been split across smaller components:
  - `dashboard/components/evidence_result_view.py` only orchestrates result tabs.
  - `dashboard/components/timing_chart.py` owns timing chart rendering and timing summary.
  - `dashboard/components/simulation_tables.py` owns external device, IP/node power, DMA BW, timing, and timeline tables.
  - `dashboard/components/evidence_debug_trace.py` owns Debug Trace tables.
  - `dashboard/components/evidence_compare.py` owns preview-vs-saved comparison rows/UI.
- Simulation preview results are not saved by default. Users must click Confirm & Save Evidence before a preview becomes persisted evidence.
- Evidence Dashboard table rendering now uses row-count-based dataframe height via `dashboard/components/table_actions.py`, so table vertical scroll should generally be avoided and page-level scroll should be used instead.
- Debug Trace now exposes formula-level detail:
  - KPI formulas.
  - IP power / DVFS / performance trace.
  - IP power formula detail, including `unit_power_mw_mp`, `resolution_mp`, voltage scale, FPS scale, and `result_mw`.
  - DMA bandwidth trace.
  - DMA bandwidth / power formula detail, including `bw_formula`, `bw_power_formula`, `bw_power_ma_formula`, `bw_mbs`, `bw_power_mw`, and `bw_power_ma`.
  - Timing / OTF group trace with `span_ms`.
  - Timing cadence, critical path, and wait/slack trace tables.
- Power formula currently interprets `unit_power_mw_mp` as a reference value at `REFERENCE_VOLTAGE_MV = 710mV` and `REFERENCE_FPS = 30`.
  - Displayed formula: `unit_power_mw_mp * resolution_mp * (set_voltage_mv / 710)^2 * (fps / 30)`.
  - If future per-project unit power data uses a different measurement voltage, add explicit per-IP/mode reference voltage metadata instead of treating `710mV` as universal.
- Exynos2600 camera recording regression coverage was expanded:
  - `cam-rec-r1-fhd30-vdis`
  - `cam-rec-r1-uhd30-vdis`
  - `cam-rec-f1-fhd30`
  - Checks include KPI, sensor mode/size/v-valid, OTF clock alignment, and cadence behavior.
- `simulation_golden_cases.yaml` now includes Exynos2600 camera recording golden entries in addition to the demo imported FHD30 case.
- The next planned work starts with **SoC extensibility cleanup**:
  - Validate SoC fixture quality by SoC/project/scenario, especially `capabilities.sim`, ppc, unit power, DVFS group, VDD, and external-device classification.
  - Separate compute IP catalog gaps from external sensor/display metadata gaps.
  - Clarify readiness severity rules: error/block vs warning.
  - Make SoC-specific default DVFS/power/capability import paths explicit and testable.
  - Keep Exynos2600 camera golden cases as the first regression guard while adding SoC-level validators.

## 2026-05-13 SoC Extensibility And Exploration API Wrap-Up

- SoC extensibility cleanup phase was implemented and committed locally after validating fixture quality/readiness rules:
  - `src/scenario_db/sim/fixture_contract.py`
  - `scripts/check_soc_sim_contract.py`
  - `docs/soc-simulation-contract.md`
  - `tests/unit/sim/test_fixture_contract.py`
- Exploration recipe and sweep foundations are now in place:
  - `src/scenario_db/sim/shape_propagation.py`
  - `src/scenario_db/sim/exploration.py`
  - `src/scenario_db/sim/exploration_runner.py`
  - `scripts/compile_exploration_recipe.py`
  - `scripts/compile_exploration_sweep.py`
  - `docs/exploration-simulation-workflow.md`
- Shape propagation is opt-in through `sim.inherit_shape` / `sim.shape_propagation`. Existing production fixtures are not auto-mutated by this path.
- Exploration recipes automatically enable inherited shape and support source shape, crop, scale, output format, port-level RDMA/WDMA/CIN/COUT, mapping provenance, and preview-only sweep comparison.
- Exploration examples were added under `demo/exploration_fixtures`:
  - camera OTF chain FHD30
  - camera crop/scale M2M
  - camera multi-output fanout
  - codec/display path
  - camera FPS/format sweep
  - camera scale/compression sweep
- Korean usage guide is available at `docs/exploration-fixture-guide-ko.md`.
- Exploration API contract and endpoints were added:
  - `docs/exploration-api-contract.md`
  - `GET /api/v1/exploration/examples`
  - `GET /api/v1/exploration/examples/{example_id}`
  - `POST /api/v1/exploration/recipes/compile`
  - `POST /api/v1/exploration/sweeps/compile`
  - `POST /api/v1/exploration/sweeps/preview`
- Exploration API is preview-first. It does not persist evidence; responses should keep `persisted=false` until a later explicit save/promote workflow is implemented.
- Latest verification before push:
  - `uv run pytest tests/unit/api/test_exploration.py -q` -> `7 passed`
  - `uv run pytest tests/unit/api -q` -> `81 passed`
  - `uv run pytest tests/unit/sim/test_exploration.py tests/unit/sim/test_exploration_runner.py tests/unit/sim/test_exploration_fixtures.py -q` -> `14 passed`
  - `uv run pytest tests/unit -q` -> `438 passed`
- Local commits after `a3d9539` were prepared for GitHub push:
  - `48f1346 Add SoC simulation fixture contract validator`
  - `2f3253c Add exploration recipe and shape propagation foundation`
  - `2b1ef99 Complete exploration simulation backend foundations`
  - `b9fcc88 Add exploration fixture examples`
  - `4e8500e Document exploration fixture usage in Korean`
  - `914f8af Add exploration API contract and endpoints`
- Next likely work:
  - Add Streamlit Exploration Workbench page using the existing Evidence Dashboard result viewer components.
  - Add candidate comparison UI for sweep results.
  - Add explicit save/promote flow only after user confirmation, keeping preview and persisted evidence separated.
  - Expand API/dashboard tests around exploration examples, compile, and preview result rendering.
