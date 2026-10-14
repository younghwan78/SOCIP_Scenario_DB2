# Scenario What-if and experiment records

Status: Current. Scope: condition planning, comparison, and frozen experiments.

All paths use `/api/v1/scenario-whatif`. Targets and saved-record reads require
reader/analyst/writer/admin. Planning, calculation, and saving require
analyst/writer/admin. Actor identity comes from the API principal.

| Endpoint | Behavior |
| --- | --- |
| `GET /targets` | Active size anchors, eligible nodes, streams, registered change kinds, model capability, and baseline hash for an explicit project/scenario/variant. |
| `POST /plan` | Interpret a bounded Korean/English question into changes, ignored clauses, or one-click clarification choices. Relative clocks calculate the baseline Timing Budget; nothing is persisted. |
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

Natural-language planning uses a bounded grammar without an external LLM, accepting
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
