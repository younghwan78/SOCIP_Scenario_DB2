# Architecture analysis API

Status: Current. Scope: stage timing budget, architecture exploration, predictions, and reports.

All paths use `/api/v1`. Reads follow the existing unauthenticated read API policy.
Timing analysis and run creation require analyst/writer/admin; promotion and report
creation/status changes require writer/admin. Actor identity comes from the API principal.

- `POST /timing-budget/variant`: analyze one scenario/variant without persistence.
- `POST /timing-budget/fleet`: analyze at most 200 variants of one scenario. Duplicate
  selections are collapsed; implicit selection also obeys the limit. Derived variants
  are excluded by their parent reference and legacy generated-name markers unless included.
- `POST /arch/exploration/runs`: persist a bounded exploration of one project. Supply
  scenario IDs or category, optionally project/variant filters. A conflicting SoC or
  mixed-project selection is rejected. The response distinguishes successful variants
  and per-variant errors; an entirely failed run is not stored.
- `GET /arch/exploration/runs[/{id}]`: list run metadata or retrieve frozen details.
  Lists accept `project_ref`. Run creation and detail support `view=summary` for compact
  per-variant rows; `/runs/{id}/variants/{scenario_id}/{variant_id}` returns full variant details.
  `/runs/{id}/manifest` returns content-addressed resolved config, simulation inputs,
  pipeline, variant, capabilities, and DVFS inputs.
- `POST /arch/predictions/promote`: `run_id`, optional `scenario_id`, `variant_ids`,
  `case_key`, and `reason`. Omitted variant IDs select all spec-OK pairs; `[]` selects none.
  An ambiguous variant name requires `scenario_id`. A non-default case requires a reason.
  Known failed re-simulation verification prevents promotion.
  Listed Pareto candidates can be selected with `case_key` and a reason. A power budget
  with incomplete model coverage blocks explicit promotion unless the run opted out
  through `require_complete_power_for_budget=false`. `expected_project_ref` rejects
  registration when the selected project differs from the run's project.
- `GET /arch/predictions/board`, `/history`, `/{id}`, `/compare`: current values,
  immutable history, detail, and attribution. Comparison requires the same scenario/variant.
- `POST /arch/reports`: freeze a snapshot and HTML from a run's current registered
  predictions; otherwise use its recommendations, explicitly without a prediction ID.
  Creation accepts `draft` only. The conclusion and scenario table distinguish registered
  predictions from exploration recommendations, including a mixed-source power range.
- `GET /arch/reports[/{id}]`, `/{id}/html`, `/{id}/stale`: metadata, snapshot, HTML,
  and comparison of frozen prediction IDs with current IDs. HTML does not change later.
- `GET /arch/reports/{id}/xlsx`: export frozen tables as a spreadsheet with numeric cells.
- `GET /arch/reports/{id}/package`: export the frozen HTML body, a review cover, and a
  manifest containing body integrity, run/input hashes, prediction/measurement IDs,
  evaluation coverage, and review history.
- `PATCH /arch/reports/{id}`: change status between `draft` and `published` only.
  Publishing requires nonblank `reviewer` and `note`. Each transition appends actor,
  timestamp, reviewer, and note to the review history; concurrent reviews serialize
  on the report row. Metadata exposes the latest review and total review count.
  Migration `0023` adds report review history.

Variant identity is the pair `(scenario_id, variant_id)`, including report and chart
selection. Promotion locks variant rows in canonical order before reading current
predictions. Concurrent requests form a supersession chain under the partial unique index.
Record IDs use UUIDs rather than timestamps. Migration `0021` adds scenario power options
and IQ review history; existing
run/prediction/report records remain readable.

Expensive requests use the shared simulation admission slots (429 with Retry-After),
configured frame limits, and `exploration_max_request_bytes` (413). Each variant is
bounded to 200,000 actual cases; a run evaluates at most 2,000,000 cases. Invalid
selections/model parameters return 422 and missing entities return 404. Float CPU
coefficients must have exactly four finite positive entries.

Power-option combinations share those case budgets with the formal variant. The
separate `max_sets` limit is at most 256; skipped sets are reported in notes/errors.
Option estimates do not replace the promoted formal variant. Attribution compares
two recommended cases when both exist, otherwise two baselines.

`GET /arch/power-options/reviews` filters by project/scenario. Writer/admin may use
`PUT /arch/power-options/reviews` with scenario_id, variant_id (`*` for scenario-wide),
option_key, status (`candidate`, `iq_eval`, `adopted`, `rejected`), and optional note.
Variant-specific review overrides scenario-wide review. Concurrent saves serialize
on the scenario row and preserve history, including first creation. Adoption only
records review status; applying the option to a formal variant is an authoring edit.

Power and timing remain model estimates. A known failed recommended-case verification
cannot be labelled spec OK. Unverified alternatives remain visibly unverified.
IP overhead is included once in `sw_ms`. Input hashes include adapter inputs, IP
capabilities, SoC compression catalog, config, DVFS, and exploration options.

See [the guide](../../guides/arch-exploration.md) for model limits and report regeneration.

Timing Budget can register one explicit condition with `POST /timing-budget/register`
(writer/admin, reason required) or save its timeline with `POST /timing-budget/evidence`
(analyst/writer/admin). The variant report exposes `condition_hash`, covering resolved
graph/config/DVFS/CPU inputs and timing choices. Both mutations accept optional
`expected_condition_hash` (16 lowercase hex characters); changed inputs return 409
before persistence. Display-only timeline length and what-if options are excluded.
Evidence IDs include the resolved condition and execution context; saved power/BW
and current use the report's CPU model. `/interval-distribution` samples per-frame
SW variability without changing the verdict or persisting data.

`GET /timing-budget/measured-inputs` lists measurements owned by the selected
scenario/variant. Variant, distribution, DVFS what-if, register and evidence requests
accept optional `measured: {measurement_ref, sw, clock, cpu}`. Each part is opt-in;
an all-false selection is a comparison reference. Foreign/missing references are
rejected even for compare-only mutations. CPU input requires a usable profile and
resolved CPU topology parameters (422 rather than flat-model fallback). Saved
evidence records input lineage in `derived_from` and `run_info.timing_budget`.
Freshness re-resolves measured SW values and retains original explicit overrides;
changed measurements require recalculation before a guarded mutation.

Calibration classifies measurement origin as `physical_capture`, `synthetic`, or `unknown`.
A measurement may pin its capture-time rail map with `provenance.rail_domain_map_ref`;
that profile must exist and belong to the measurement's project. Invalid pins return 422
instead of silently using a newer or foreign profile. Without a pin, the latest project
map is used and the comparison records that basis. Batched reads fetch distinct pinned
profiles in one query.
