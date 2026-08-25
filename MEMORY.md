# Project Memory

This file records repo-local implementation decisions and current state. It is not the Codex internal memory store.

## 2026-04-26 Viewer Direction

- The viewer moved from Cytoscape-style rendering toward ELK.js/SVG because SoC block diagrams need readable orthogonal routing, hierarchy groups, and professional topology/detail diagrams.
- The separately supplied legacy fixture root remains read-only and is used only as a visual/behavior reference.
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
- The read-side contract is documented in `docs/contracts/api/read-api-contract.md`.
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
  - `docs/contracts/simulation/soc-simulation-contract.md`
  - `tests/unit/sim/test_fixture_contract.py`
- Exploration recipe and sweep foundations are now in place:
  - `src/scenario_db/sim/shape_propagation.py`
  - `src/scenario_db/sim/exploration.py`
  - `src/scenario_db/sim/exploration_runner.py`
  - `scripts/compile_exploration_recipe.py`
  - `scripts/compile_exploration_sweep.py`
  - `docs/design/exploration-simulation-workflow.md`
- Shape propagation is opt-in through `sim.inherit_shape` / `sim.shape_propagation`. Existing production fixtures are not auto-mutated by this path.
- Exploration recipes automatically enable inherited shape and support source shape, crop, scale, output format, port-level RDMA/WDMA/CIN/COUT, mapping provenance, and preview-only sweep comparison.
- Exploration examples were added under `demo/exploration_fixtures`:
  - camera OTF chain FHD30
  - camera crop/scale M2M
  - camera multi-output fanout
  - codec/display path
  - camera FPS/format sweep
  - camera scale/compression sweep
- Korean usage guide is available at `docs/guides/exploration/exploration-fixture-guide-ko.md`.
- Exploration API contract and endpoints were added:
  - `docs/contracts/api/exploration-api-contract.md`
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

## 2026-05-17 Exploration Workbench Wrap-Up

- Current pushed GitHub head for the exploration wrap-up is `7883931 Add exploration pyramid sweep comparison` on branch `codex/fix-csis-sbwc-clock-formula`.
- Exploration Workbench is considered **1st-pass complete** for the current scope:
  - Example list/load, YAML upload, editable YAML input, and input hide/show are available.
  - Single Design and Batch Exploration templates are available from the sidebar.
  - Compile and Run Simulation are preview-only; results are not persisted as evidence.
  - Preview Results show candidate comparison, selected candidate detail via the shared evidence result viewer, and topology/port-flow debugging.
- Candidate comparison UI now emphasizes sweep-level decision making:
  - Baseline candidate can be selected and deltas are recomputed against that baseline.
  - Feasible-only, Pareto-only, and hide-warning filters are available.
  - KPI Distribution by Sweep uses horizontal box plots for Power, DMA BW, and HW Time.
  - The graph focuses on distribution, default, min, and max instead of rendering every candidate as a long bar list.
  - The graph is followed by a min/default/max/spread summary table with metric-specific row tinting and default-row emphasis.
  - Full candidate comparison table remains below for detailed inspection.
- Added complex pyramid SBWC sweep fixture:
  - `demo/exploration_fixtures/sweeps/camera_pyramid_sbwc_sweep.yaml`.
  - Models HP2 FHD30 recording-style pyramid path with CSIS/PDP/BYRP/RGBP/YUVP/MLSC/MTNR/MSNR/MCSC roles.
  - MLSC L0/L1/L2/L3/G4 SBWC on/off axes generate 32 preview candidates.
  - The fixture preserves multi-output MLSC and multi-RDMA MTNR port conditions for BW/power preview, while the current exploration compiler still keeps the main canonical edge path linear.
- Sweep axis handling was extended:
  - `axes[].values[]` can use `{label, value}` to apply object-valued changes while keeping readable variant ids.
  - This is used when one sweep choice must update a full port descriptor, such as `compression` and `comp_ratio` together.
  - Non-merged sweep documents now get unique scenario ids derived from variant id to avoid duplicate import-document validation failures.
- Compression handling was corrected:
  - `COMP_OFF` and other disabled/off compression labels ignore `comp_ratio`.
  - Exploration compiler omits `comp_ratio` from compiled sim ports when compression is disabled.
  - BW calculation and debug trace use the same effective compression-ratio logic.
  - `COMP_SBWC_LOSSLESS` with `comp_ratio: 0.5` remains the SBWC case for pyramid sweep outputs.
- Documentation updated:
  - `docs/guides/exploration/exploration-fixture-guide-ko.md` documents Workbench operation, topology/port-flow debugging, candidate comparison behavior, and the new pyramid SBWC example.
  - `demo/exploration_fixtures/README.md` lists the new sweep example.
- Latest verification before/after push:
  - `uv run pytest tests/unit/dashboard -q` -> `40 passed`
  - `uv run pytest tests/unit -q` -> `465 passed`
  - API and Streamlit were restarted and checked on FastAPI `127.0.0.1:18000` and Streamlit `127.0.0.1:18502`.
- Workbench follow-up candidates are no longer blocking for the current scope:
  - Mapping profile catalog and project/SoC mapping selection.
  - Large sweep job/progress/retry management.
  - Optional export/import workflow for selected candidates.
  - More accurate fanout/fanin canonical topology compiler if exploration graph fidelity becomes a priority.
- Recommended next major work returns to **SoC extensibility cleanup**:
  - SoC-specific fixture/capability validation.
  - Native unit power/PPC/DVFS import paths.
  - Readiness rules for missing compute IP metadata vs external sensor/display metadata.
  - Additional SoC/project exploration fixtures guarded by regression tests.

## 2026-05-17 Chain Template / SoC Extensibility Start

- Added first-pass versioned chain template support for complex SoC/ISP topology authoring.
- New compact template contract:
  - `kind: scenario.chain_template`
  - immutable `id + version`
  - `schema_version`
  - compact `buffer_columns` tuple syntax, for example `[x, y, width, height, format, bitwidth, compression, comp_ratio]`
  - compact port-level link syntax, for example `"mlsc:WDMA0 -> L0 | M2M"`
  - `derive_from + scale` buffer derivation for pyramid buffers.
- New implementation:
  - `src/scenario_db/sim/chain_templates.py`
  - `normalize_chain_template(...)`
  - `compile_chain_template(...)`
  - `run_chain_template_preview(...)` through the existing exploration preview path.
- New API endpoints:
  - `POST /api/v1/exploration/templates/compile`
  - `POST /api/v1/exploration/templates/preview`
  - `GET /api/v1/exploration/examples` now includes `template:*` examples.
- Exploration Workbench now detects `scenario.chain_template` YAML as `Chain Template` and can compile/run preview through the new template endpoints.
- Added complex template fixture:
  - `demo/exploration_fixtures/templates/camera_recording_pyramid_v1.yaml`
  - Models HP2 recording-style chain with CSIS/PDP/BYRP/RGBP/YUVP/MLSC/MTNR/MSNR/MCSC/DPU/CODEC, multi-WDMA MLSC, multi-RDMA MTNR, and L0/L1/L2/L3/G4 pyramid buffers.
- Added documentation and CLI:
  - `docs/contracts/data/chain-template-contract-ko.md`
  - `scripts/compile_chain_template.py`
  - `demo/exploration_fixtures/README.md` updated with template usage.
- Verification:
  - `uv run pytest tests/unit/sim/test_chain_templates.py tests/unit/sim/test_exploration_fixtures.py tests/unit/api/test_exploration.py tests/unit/dashboard/test_exploration_workbench.py -q` -> `38 passed`
  - `uv run python scripts/compile_chain_template.py demo/exploration_fixtures/templates/camera_recording_pyramid_v1.yaml --normalized-output .runlogs/camera_recording_pyramid.normalized.yaml --output .runlogs/camera_recording_pyramid.compiled.yaml --bundle-output .runlogs/camera_recording_pyramid.bundle.json` -> passed
  - `uv run pytest tests/unit -q` -> `471 passed`

## 2026-05-17 Chain Template Sweep Support

- Added `scenario.chain_template_sweep` support so a versioned compact chain template can be expanded across axis values.
- Current sweep behavior intentionally emits one scenario document per candidate because candidate axis values may change scenario-level `pipeline.buffers`.
- New implementation:
  - `compile_chain_template_sweep(...)` in `src/scenario_db/sim/chain_templates.py`
  - `run_chain_template_sweep_preview(...)` in `src/scenario_db/sim/exploration_runner.py`
  - `scripts/compile_chain_template_sweep.py`
- New API endpoints:
  - `POST /api/v1/exploration/template-sweeps/compile`
  - `POST /api/v1/exploration/template-sweeps/preview`
  - example discovery now includes `template_sweep:*`.
- Exploration Workbench now detects `kind: scenario.chain_template_sweep` as `Template Sweep` and routes compile/run simulation to the new endpoints.
- Added fixture:
  - `demo/exploration_fixtures/template_sweeps/camera_recording_pyramid_sbwc_template_sweep.yaml`
  - 4-case L0/L1 SBWC on/off sweep over the camera recording pyramid template.
- Documentation updated:
  - `docs/contracts/data/chain-template-contract-ko.md`
  - `demo/exploration_fixtures/README.md`
- Verification:
  - `uv run pytest tests/unit/sim/test_chain_templates.py tests/unit/sim/test_exploration_fixtures.py tests/unit/api/test_exploration.py tests/unit/dashboard/test_exploration_workbench.py -q` -> `42 passed`
  - `uv run python scripts/compile_chain_template_sweep.py demo/exploration_fixtures/template_sweeps/camera_recording_pyramid_sbwc_template_sweep.yaml --bundle-output .runlogs/camera_recording_pyramid_template_sweep.bundle.json --cases-output .runlogs/camera_recording_pyramid_template_sweep.cases.json` -> passed
  - `uv run pytest tests/unit -q` -> `475 passed`
