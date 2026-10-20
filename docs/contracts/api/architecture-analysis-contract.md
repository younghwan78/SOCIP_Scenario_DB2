# Architecture analysis API

Status: Current. Scope: stage timing budget, architecture exploration, predictions, and reports.

All paths use `/api/v1`. Reads follow the existing unauthenticated read API policy.
Timing analysis and run creation require analyst/writer/admin; promotion and report
creation/status changes require writer/admin. Actor identity comes from the API principal.

Prediction notes are separate from frozen calculation metrics. Note/comment reads require reader/analyst/writer/admin authentication (or the deployment's local auth bypass). Historical catalog versions are not inferred from today's mutable catalog rows; missing version stamps are shown as unknown. SW is labeled measured only when measured SW was selected as input. `GET/PUT
/arch/predictions/{id}/notes` exposes title, purpose, description, assumptions,
conclusion, tags, actor/time metadata, and revision. PUT requires writer/admin and
`expected_revision` (0 for first creation); stale revisions return 409. First saves
serialize on the prediction row. `GET/POST /arch/predictions/{id}/comments` provides
bounded pagination and append-only comments/replies. POST requires analyst/writer/admin;
reply parents must belong to the same prediction, enforced by a composite FK.
Comments are listed by a database-generated registration sequence, including when
timestamps are equal or application-server clocks differ.
Migration `0024_prediction_collaboration` adds these collaboration tables.

Promote/lever requests optionally provide `expected_current` entries containing
`scenario_id`, `variant_id`, and nullable `prediction_id`. When present they must
cover all selected pairs; null expects no current prediction. The server checks
the reviewed IDs after canonical variant-row locks and before any promotion.
Changed current IDs return 409 atomically. Timing Budget registration accepts
`expected_current_prediction_id`; explicit null also guards first registration.
Recompute automatically guards its target ID during promotion. Callers omitting
the new preconditions retain the existing API behavior.

Guarded lever registration retains scenario/variant locks through IQ reviews,
exploration, and promotion, with one final commit and rollback on failure.
The scenario uses `FOR NO KEY UPDATE`, compatible with prediction FK key-share
locks, to avoid cycles with ordinary promotion. Valid rejected IQ results retain
their existing recorded-review behavior.

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
  Alternatively, supply `project_ref` without `run_id` for a project report spanning
  all scenario types and current predictions across runs. Unregistered variants use
  their newest evaluation, including calculation errors; older successes never hide
  a newer failed calculation. Source runs remain listed in the snapshot. A project
  report cannot specify `scenario_type`, because it updates the project-wide risk
  register. A run report keeps its own risk snapshot without updating that register.
- `GET /review/risks?project_ref=...` reads the project risk register. Writer/admin
  may `PATCH /review/risks/{id}` with `owner`, `status`, and `note`; changes keep
  actor/time history. Status is `open`, `watch`, `mitigating`, `accepted`, or `closed`.
  Project reports refresh automatic rules; absent rules become resolution candidates
  for human confirmation. IDs and human annotations persist across reports. First
  creation serializes on the project row. Migration `0028` adds `review_risks`.
- `GET /calibration/summary` accepts `scenario_id`, `project_ref`, and
  `include_synthetic` (default true). Both scope filters apply when supplied together.
  It selects one representative capture per variant, reports category bias,
  correction previews and confidence, and distinguishes physical, synthetic and
  unknown origins. Synthetic captures do not count as silicon validation evidence.
  `GET /calibration/measurements` also accepts `project_ref`; the UI applies the
  same project and synthetic filters to the capture list and model summary.
  Calibration and report capture selection share this order: total-power value
  present (including zero), physical capture over unknown over synthetic, newest
  measurement time, then ascending evidence ID. Missing time sorts oldest.
  Total power means a scalar or `mean` value, not complete KPI coverage.
  Previous-project reference source-priority/mapping rules remain separate.
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

`POST /calibration/power-fit` (analyst/writer/admin) proposes CPU/IP/BW factors for
up to 500 measurements in one project, optionally narrowed to one scenario. Base
parameters must belong to the project's SoC. Synthetic measurements are excluded
by default; including synthetic or unknown-origin measurements never makes a
factor recommended.
`POST /calibration/power-params` (writer/admin) creates a draft version without
modifying the base. Source references must resolve to measurements of that SoC;
synthetic lineage is derived from stored provenance. Factors must be finite and
within 0.2–5. IP calibration scales both keyed and fallback factors. BW calibration
requires linear-per-gbps or mif-linear parameters. Version allocation is serialized
per SoC. `GET /calibration/power-params?soc_ref=...` lists available versions.

`POST /arch/predictions/{prediction_id}/recompute` (writer/admin) re-registers a
current prediction using its stored condition; optional `power_params_ref` selects
new parameters and `reason` records the change. Measured SW values are re-read while
explicit runtime overrides are retained. New Timing Budget registrations preserve
explicit default-valued choices. Exploration recompute retains reference power
budgets; manually selected exploration cases are skipped. Superseded predictions
return 422.

### Model basis registry

`/bases` stores project-scoped, numbered model inputs (configuration profile,
power parameters, DVFS, engine). Creation captures component versions and content
hashes, including the selected default DVFS table. Editing a referenced catalog
entry requires a new basis: calculation, activation and promotion reject changed
inputs with 422. Parent bases and components must belong to the selected project
and SoC. Explicit input overrides remain visible as an ad-hoc basis (`B3*`).

Creation and activation are serialized per project. Draft trials keep a restart
token and merge concurrent item results under the same project lock. A result
from an earlier trial returns 409 instead of updating a restarted trial. Promotion
requires at least one successful calculation; pending or failed items retain their
current predictions, and predictions changed since the trial are reported as stale.

`GET /bases/{basis_id}` returns the basis, current catalog component details,
input drift, trial summary and current prediction counts (including overrides).
When inputs have changed, component details describe today's catalog values;
the basis preserves its original input stamp. Timing Budget responses also return
the resolved `basis_ref`, `basis_code` and `basis_overrides`.

`GET /calibration/coverage` returns evidence and basis information without
recalculating freshness by default. Set `freshness=true` to include freshness,
or fetch `/arch/predictions/freshness` separately to avoid delaying the table.

## Tiered review report (RPT-08..12)

Snapshots with `criteria` render as Tier 1 (결론 · Risk register · 이전 보고서 대비),
Tier 2 area sections whose first line is the area's conclusion (성능 · Timing, Power 구성
with the previous-project dumbbell, Lever · 발열, CPU · SW, 예측 ↔ 실측 with rail bias,
분류별 의견, 검토 범위) and Tier 3 (Scenario dossier, 요약 표, 변경 이력, 부록). Long tables show
the top 10 with the full table folded (`details.more`, hidden in print). Project reports
freeze `snapshot.previous` (`reporting.report_diff`): new / reopened / resolved risks, power
changes ≥ 1 mW, criteria / basis / policy / CPU tolerance changes against the previous
project report of the same project.

## Calibration drill-down (CAL-09..11)

`GET /calibration/measurements/{id}` adds `drilldown`: rail groups (IP per vdd from the
simulation `dvfs_breakdown`, CPU, BW, unmodeled) with Δ mW / Δ% / error share, latency
(prediction video latency vs measured p95), SW task p95 vs the defined timing at the
prediction statistic with stage margin, and predicted IP clock per DVFS group vs measured
residency. `GET /calibration/summary` adds per-row `rail_groups` / `latency`, `rail_bias`
and `latency_bias`.
