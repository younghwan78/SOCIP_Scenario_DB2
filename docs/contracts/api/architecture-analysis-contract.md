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
- `POST /arch/predictions/promote`: `run_id`, optional `scenario_id`, `variant_ids`,
  `case_key`, and `reason`. Omitted variant IDs select all spec-OK pairs; `[]` selects none.
  An ambiguous variant name requires `scenario_id`. A non-default case requires a reason.
  Known failed re-simulation verification prevents promotion.
- `GET /arch/predictions/board`, `/history`, `/{id}`, `/compare`: current values,
  immutable history, detail, and attribution. Comparison requires the same scenario/variant.
- `POST /arch/reports`: freeze a snapshot and HTML from a run's current registered
  predictions; otherwise use its recommendations, explicitly without a prediction ID.
- `GET /arch/reports[/{id}]`, `/{id}/html`, `/{id}/stale`: metadata, snapshot, HTML,
  and comparison of frozen prediction IDs with current IDs. HTML does not change later.
- `PATCH /arch/reports/{id}`: change status between `draft` and `published` only.

Variant identity is the pair `(scenario_id, variant_id)`, including report and chart
selection. Promotion locks variant rows in canonical order before reading current
predictions. Concurrent requests form a supersession chain under the partial unique index.
Record IDs use UUIDs rather than timestamps. The migration remains `0020`; existing
run/prediction/report records remain readable.

Expensive requests use the shared simulation admission slots (429 with Retry-After),
configured frame limits, and `exploration_max_request_bytes` (413). Each variant is
bounded to 200,000 actual cases; a run evaluates at most 2,000,000 cases. Invalid
selections/model parameters return 422 and missing entities return 404. Float CPU
coefficients must have exactly four finite positive entries.

Power and timing remain model estimates. A known failed recommended-case verification
cannot be labelled spec OK. Unverified alternatives remain visibly unverified.
IP overhead is included once in `sw_ms`. Input hashes include adapter inputs, IP
capabilities, SoC compression catalog, config, DVFS, and exploration options.

See [the guide](../../guides/arch-exploration.md) for model limits and report regeneration.
