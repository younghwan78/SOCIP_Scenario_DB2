# Scenario What-if and experiment records

Status: Current. Scope: condition planning, comparison, and frozen experiments.

All paths use `/api/v1/scenario-whatif`. Targets and saved-record reads require
reader/analyst/writer/admin. Planning, calculation, and saving require
analyst/writer/admin. Actor identity comes from the API principal.

| Endpoint | Behavior |
| --- | --- |
| `GET /targets` | Active size anchors, eligible nodes (with baseline applied clock and DVFS domain), streams, DVFS `domains` (resolved level, member IPs, OPP ladder slow→fast), registered change kinds, `asks`, `llm` availability, model capability, and baseline hash for an explicit project/scenario/variant. |
| `POST /targets` | Same discovery using supplied `config`/`options`, including reopened experiment settings. Both target routes calculate a baseline under simulation admission/frame limits. |
| `POST /ask` | One request → executed answer. Builder input (`ask` + `changes` / `search_domains`) runs directly; a `query` alone is interpreted by the in-house LLM into the same form. Returns `interpretation`, executed `plan`, `answer` (verdict, headline, facts, follow-up actions) and `result` / `search` / `diagnose`. Nothing is persisted. |
| `POST /plan` | Legacy bounded-grammar interpretation (kept for API compatibility; the UI no longer uses it). |
| `POST /preview` | Compare a baseline and detached candidate using the Timing Budget engine. |
| `POST /experiments` | Recalculate and freeze the reviewed request, results, explanation, question, and actor; returns 201. |
| `GET /experiments` | Paginated records visible to the principal within the selected project/scenario/variant. |
| `GET /experiments/{id}` | Frozen record and request for rerunning its conditions. |
| `POST /sweeps` | Bounded value grid on one baseline; constraint eligibility, Pareto IDs and reproducible row preview requests. |
| `POST /jobs` | Same sweep request, durable actor-owned job (202). Identical resolved requests from the same actor reuse a job. |
| `GET /jobs/{id}` | Status, progress and completed rows; another actor receives 404. |
| `POST /jobs/{id}/cancel` | Cooperative stop between cases; completed rows remain available. |
| `POST /jobs/{id}/resume` | Resume cancelled, failed or lease-expired work, after current input identity validation. |

## Conditions and result meaning

Scope always includes `project_ref`, `scenario_id`, and `variant_id`. The server
checks scenario ownership. Available changes are discovered from the selected
graph and Timing Budget model; capability notes distinguish a reviewed platform
profile from generic policy and do not certify model calibration.

Target interpretation and candidate execution within one request share its
resolved baseline. A separate preview or save resolves current inputs again
with the unchanged preview contract (validation as the preview request,
expected-baseline check before timing evaluation); request-local reuse never
bypasses the expected-baseline check on saving.

Supported changes: `anchor_size`, `output_size`, eligible `node_size`, `fps`, and
`node_clock_mhz`, anchorless `stream_size`, and modeled `node_param` settings.
The `change_kinds` registry supplies labels, selectors, choices, and bounds to the UI.
Stream changes resize surfaces grouped by their original size, preserving display
destination/panel geometry. Unmodeled parameters are not offered.
Each dimension is 16–16384 pixels; FPS is positive and at most
240; the manual clock lower bound is positive and at most 5000 MHz. At most eight changes are accepted.
Duplicate/overlapping size targets, ambiguous multi-port
resizing, and extrapolation of measured timing/CPU/clock inputs are rejected.

Commercialization levers (`whatif_levers.py`, same registry; `group` = palette group, `iq: required`
= adoption needs image-quality evaluation):

| target | selector · value | effect |
| --- | --- | --- |
| `sensor_mode` | `node_id` (active sensor) · `option` = `<ip_ref>#<mode>` | Another catalog sensor / DT mode with `sensor_fps` ≥ scenario FPS. Readout timing follows the mode; when the active size differs, downstream IPs, their anchors (pyramid levels by 2^-k) and explicit buffer sizes are reshaped |
| `sensor_binding` | `node_id` · full `sensor_binding` from targets | Pins source catalog/lineup hashes, board config, slot and DT mode label. Revalidates installed source, single-image transport, timing when present, and final FPS. Target-board wiring remains unverified. |
| `chain_size` | `node_id` · `width`/`height` · optional `operation`, `port`, `x`, `y` | Only declared crop/scale operations are accepted. Checks ROI, alignment, format and declared bounds. Propagates along selected data ports, stopping at fixed geometry; preserves final output surfaces. The IP keeps its input size. |
| `power_knob` | `param` (knob) · `option` (value) | Scenario `power_options.knobs` with `explore` (e.g. `crop_strategy=byrp_bcrop`, `pyramid_l0=skip`), applied with the authoring knob engine |
| `history_interval` | optional `buffer_id` (none = all history buffers) · `value` N (1–8) | Previous-frame DMA read/write once every N frames: `history.update_interval` → `r_w_rate = 1/N`. IP core work stays per frame |
| `ip_mode` | `node_id` · `option` (mode) | IP catalog `capabilities.sim.modes.<mode>` (own unit power / PPC) |
| `compression` | `buffer_id` · `option` (`COMP_OFF` or a SoC catalog mode of the buffer family) · optional `value` ratio (0, 1] | Ratio default: `typical_ratio` → catalog `comp_ratio` < 1 → assumed. Only buffers whose endpoint IPs declare compression are listed; a mode the IP catalog does not list is rejected |

Structural levers apply first (sensor → power option → chain size), then the rest in request order.
An explicitly selected sensor mode must also support the final FPS after all conditions are applied. Plain FPS-only conditions remain hypothetical cadence changes.
Preview adds `lever_notes` (what was reshaped) and `iq_required` (targets needing IQ evaluation;
lossy compression included).

`dvfs_level` pins a DVFS domain to an OPP level of that domain's ladder (`domain` + integer `level`);
every IP of the shared domain runs at that level, so a level below the required clock fails timing.
Unlike `node_clock_mhz` (a manual lower bound that cannot lower the applied clock), it can move a
domain down.

### Ask (`POST /ask`)

| `ask` | Input | Execution | Answer |
| --- | --- | --- | --- |
| `what_if` | `changes` (1–8) | Preview (baseline vs candidate) | `ok` / `fail` + minimum stage slack, power/BW deltas, applied clock moves; notes a clock floor below the applied clock |
| `combine` | `changes` (2–8; `combine: "factorial"` ≤ 5) | Baseline + each lever alone + all together (`each`) or every subset (`factorial`), each case through `apply_whatif_changes` + Timing Budget | `combine.rows` (Δ CPU/IP/memory/BW, verdict, min slack, notes), `best` = fps-feasible lowest power, `interaction_mw` = all − Σ singles |
| `search_limit` | `search_domains` (empty = all) | Lower each domain one OPP level at a time until the Timing Budget verdict fails | Lowest feasible level, power delta, first failing level and reason; `at_min` when already at the lowest OPP |
| `diagnose` | — | Baseline report | Tightest stage and slack, its longest IPs, per-domain room to lower/raise |

All numbers come from the Timing Budget engine; the answer text is composed on the server from them.
Unknown search domains are rejected; an omitted domain list means all available domains.
The upper bound on evaluated search / combine cases must fit `exploration_max_cases`.
Duplicate targets and fields incompatible with the selected question kind are rejected.
Malformed LLM envelopes or conflicting conditions return `llm_unavailable`; invalid
relative values and unavailable OPPs do not become executable conditions.

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

## Reproducible comparison and value grids

Model settings accept `basis_ref` and `comparison: retune | fixed_opp` (default
`retune`). Fixed OPP keeps the original baseline and applies its domain levels to
the candidate only. It is supported by single-candidate preview/ask and sweeps;
explicit DVFS-level changes cannot be combined with that policy. Each sweep row
includes its complete `preview_request`, so detail calculation and saving retain
the policy and original baseline settings.

Targets expose `analysis_hash`, baseline metrics/coverage and model lineage.
`expected_analysis_hash` is optional for backward compatibility; the UI supplies it
to reject model/config/table drift with 409. The graph hash remains separately
available. Candidate condition hashes include resolved inputs and comparison policy.

A sweep has 1–4 `axes`, each with a label and 2–12 distinct `WhatIfChange` values
for one target. Fixed `changes` and axis targets must be distinct, at most eight
in total. The product is at most 256 and also respects the deployment case limit.
Constraints are `max_power_mw`, `max_bw_mbs`, `max_latency_ms`, `min_slack_ms` and
`allow_iq_required` (default false). Failed cases remain visible with reasons.
Eligibility requires timing feasibility, complete IP models and the selected
constraints. The Pareto set minimizes modeled power, BW and latency; the recommended
row is the lowest modeled-power eligible row. Neither selection certifies IQ.

Sensor power is reported separately. A measured sensor sample requires explicit
power, source and matching FPS; otherwise it stays unknown. Rankings and power
constraints use CPU + IP + memory subtotal, excluding unmodeled device power.
Assumed SW runtime and bitstream bitrate remain fixed and visible in warnings.

Migration `0032` adds job requests/checkpoints. A two-worker thread pool
uses the existing simulation admission budget; the database queue is bounded to 16
active jobs. A 120-second heartbeat lease and worker tokens fence obsolete workers.
Restarted or cancelled work can resume only with the same input identity. Progress
is checkpointed between cases; cancellation does not interrupt a case mid-calculation.
Serialized requests preserve omitted configuration fields so active-profile defaults
remain distinguishable from explicitly supplied code defaults after reopening.
Worker calculation sessions release read connections before computing/checkpointing.

Pure case caching is opt-in through `SCENARIO_DB_WHATIF_CASE_CACHE_ENTRIES`
(default 0, maximum 256) and `_TTL_SECONDS` (default 60). Keys include resolved
graph/config/options/DVFS inputs and engine revision; cached values are copied for
caller isolation. Ownership, selection and hash validation always run before reuse.

## Persistence and access

Migration `0024_prediction_collaboration` adds `whatif_experiments`. Frozen experiments are separate from
formal variants and current predictions; saving does not promote a prediction.
`private` records are readable only by their principal; `shared` records are readable
by authenticated readers under the deployment's existing project/network policy.
Unauthorized private IDs return 404. Local authentication bypass uses one local
subject and does not distinguish people. Pagination uses bounded limit/offset and
stable timestamp/ID order.

Planning/preview/save remain synchronous and reuse admission slots, request bounds,
and frame limits. Value-grid jobs are durable and use the same computation limits.
Experiment lists project only summary metrics from JSON; detail reads retain the
complete frozen result.

See [the user guide](../../guides/prediction-collaboration-whatif.md).
