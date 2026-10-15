# Scenario What-if and experiment records

Status: Current. Scope: condition planning, comparison, and frozen experiments.

All paths use `/api/v1/scenario-whatif`. Targets and saved-record reads require
reader/analyst/writer/admin. Planning, calculation, and saving require
analyst/writer/admin. Actor identity comes from the API principal.

| Endpoint | Behavior |
| --- | --- |
| `GET /targets` | Active size anchors, eligible nodes (with baseline applied clock and DVFS domain), streams, DVFS `domains` (resolved level, member IPs, OPP ladder slow→fast), registered change kinds, `asks`, `llm` availability, model capability, and baseline hash for an explicit project/scenario/variant. |
| `POST /ask` | One request → executed answer. Builder input (`ask` + `changes` / `search_domains`) runs directly; a `query` alone is interpreted by the in-house LLM into the same form. Returns `interpretation`, executed `plan`, `answer` (verdict, headline, facts, follow-up actions) and `result` / `search` / `diagnose`. Nothing is persisted. |
| `POST /plan` | Legacy bounded-grammar interpretation (kept for API compatibility; the UI no longer uses it). |
| `POST /preview` | Compare a baseline and detached candidate using the Timing Budget engine. |
| `POST /experiments` | Recalculate and freeze the reviewed request, results, explanation, question, and actor; returns 201. |
| `GET /experiments` | Paginated records visible to the principal within the selected project/scenario/variant. |
| `GET /experiments/{id}` | Frozen record and request for rerunning its conditions. |

## Conditions and result meaning

Scope always includes `project_ref`, `scenario_id`, and `variant_id`. The server
checks scenario ownership. Available changes are discovered from the selected
graph and Timing Budget model; capability notes distinguish a reviewed platform
profile from generic policy and do not certify model calibration.

Supported changes: `anchor_size`, `output_size`, eligible `node_size`, `fps`, and
`node_clock_mhz`, anchorless `stream_size`, and modeled `node_param` settings.
The `change_kinds` registry supplies labels, selectors, choices, and bounds to the UI.
Stream changes resize surfaces grouped by their original size, preserving display
destination/panel geometry. Unmodeled parameters are not offered.
Each dimension is 16–16384 pixels; FPS is positive and at most
240; the manual clock lower bound is positive and at most 5000 MHz. At most eight changes are accepted.
Duplicate/overlapping size targets, sensor-mode changes, ambiguous multi-port
resizing, and extrapolation of measured timing/CPU/clock inputs are rejected.

`dvfs_level` pins a DVFS domain to an OPP level of that domain's ladder (`domain` + integer `level`);
every IP of the shared domain runs at that level, so a level below the required clock fails timing.
Unlike `node_clock_mhz` (a manual lower bound that cannot lower the applied clock), it can move a
domain down.

### Ask (`POST /ask`)

| `ask` | Input | Execution | Answer |
| --- | --- | --- | --- |
| `what_if` | `changes` (1–8) | Preview (baseline vs candidate) | `ok` / `fail` + minimum stage slack, power/BW deltas, applied clock moves; notes a clock floor below the applied clock |
| `search_limit` | `search_domains` (empty = all) | Lower each domain one OPP level at a time until the Timing Budget verdict fails | Lowest feasible level, power delta, first failing level and reason; `at_min` when already at the lowest OPP |
| `diagnose` | — | Baseline report | Tightest stage and slack, its longest IPs, per-domain room to lower/raise |

All numbers come from the Timing Budget engine; the answer text is composed on the server from them.

Natural-language input (`query` without `ask`/`changes`) is sent to an in-house OpenAI-compatible
`POST {SCENARIO_DB_WHATIF_LLM_BASE_URL}/chat/completions` (`_MODEL`, optional `_API_KEY`,
`_TIMEOUT_S`, `_JSON_MODE`; `response_format` is dropped and retried once when the server rejects
it). The request carries the question and the variant's target catalog only. The model returns a
plan in the builder's vocabulary; relative forms (`shift`, `pin: min|max`, clock `scale`) are
resolved against the baseline ladder/clock, then every change is validated like builder input.
Unknown targets are listed in `interpretation.ignored`; a step past the lowest/highest OPP becomes
an `interpretation.boundaries` message and a `boundary` answer with the current bottleneck. When the
endpoint is not configured, times out, errors, or returns non-JSON, `interpretation.status` is
`llm_unavailable` with the reason and no answer — the UI continues with the condition builder; there
is no regex fallback.

The legacy `/plan` endpoint uses a bounded grammar without an external LLM, accepting
explicit dimensions, named sizes/rates, relative size/FPS, and absolute or relative
IP clock lower bounds. `ready`, `partial`, `clarification`, `unsupported`, and
`no_change` distinguish complete conditions, supported subsets, choices, rejected
questions, and unchanged inputs. Unsupported clauses are listed in `ignored` with
reasons; they are never applied. Ambiguous clauses require a choice in the question
card; the structured editor can instead specify the exact subset to calculate.
Each emitted condition and choice satisfies preview bounds. Planning accepts
optional `config` and `options`, applies the active model defaults, and uses those
resolved inputs for relative FPS/clock values, including reopened experiments.
Users review and may edit structured conditions before calculation.

Preview requires the 64-character `expected_baseline_hash` from targets/planning.
Changed graph/capability inputs return 409. Saving additionally requires the
preview's `expected_condition_hash`; changed calculation inputs return 409.
Saved result values are calculated on the server rather than supplied by clients.

Baseline/candidate contain reports, metrics, model coverage, assumptions, and
required/applied clock comparison. `modeled_power_mw` is the modeled subtotal.
`total_power_mw` is null when excluded or missing components prevent whole-system
prediction. SW runtime per frame and bitstream bitrate retain their stated baseline
assumptions. Output resizing preserves sensor mode/input dimensions and upstream
processing. A model calculation does not establish measured accuracy or IQ.

Results retain model lineage, normalized conditions, hashes, and warnings.
Reopening an experiment loads its conditions for calculation against today's inputs.

## Persistence and access

Migration `0024_prediction_collaboration` adds `whatif_experiments`. Frozen experiments are separate from
formal variants and current predictions; saving does not promote a prediction.
`private` records are readable only by their principal; `shared` records are readable
by authenticated readers under the deployment's existing project/network policy.
Unauthorized private IDs return 404. Local authentication bypass uses one local
subject and does not distinguish people. Pagination uses bounded limit/offset and
stable timestamp/ID order.

Planning/calculation/save reuse admission slots, request bounds, and frame limits. They
remain synchronous requests rather than durable background jobs.

See [the user guide](../../guides/prediction-collaboration-whatif.md).
