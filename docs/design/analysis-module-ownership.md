# Analysis module ownership

The modules below concentrate rules shared by analysis callers. Domain terms are
defined in the [glossary](../../GLOSSARY.md). This is a structural change: public
request/response formats, stored report formats, simulation equations, selection
results, error contracts and UI state transitions are unchanged. The only intended
runtime difference is fewer repeated calculations within one request.

## Report snapshot

`reporting.arch_report.build_snapshot` receives collected `ReviewEvidence` and
returns the completed review snapshot. Its implementation attaches clock,
reference, calibration, CPU, IQ and project evidence before computing verdicts,
risks and the final conclusion. Callers do not construct intermediate snapshot
states or recompute the conclusion after adding evidence.

`api.services.arch_exploration` collects database facts and retains transaction
ownership. Run reports freeze their own risk list. Project reports synchronize
the project risk register, preserve human annotations and attach the previous
report comparison. Rendering and persistence follow those operations.

The pure snapshot interface is the test surface for assembly and evidence
isolation. PostgreSQL tests still cover scoping, locking, concurrent review and
frozen report persistence. A fake database is not a replacement for those tests.

## Representative measurement

`comparison.measurement_selection.representative_measurement` selects from
captures already scoped by its caller. Calibration and report collection use
the same ordering:

1. A total-power value is present, including zero. The rule stays caller-owned,
   as before: the report counts any non-`None` scalar or `mean`; calibration
   passes its numeric `_total` rule (`has_total=`).
2. Origin is physical capture, then unknown, then synthetic.
3. Measurement time is newest first; absent time is oldest.
4. Ties keep input order. Both callers read captures as
   `measured_at DESC NULLS LAST, id`, so ties resolve with the database order the
   report already used. Calibration previously had no `ORDER BY` (tie result was
   unspecified); it now reads with the same one.

The selector computes each capture's priority once. It does not query the
database or widen scope. Batched measurement
detail loading remains separate. Previous-project references have their own
explicit/source-priority/mapping policy and do not use this selector.

## Analysis input selection

`api.services.analysis_inputs.resolve_analysis_selection` builds a detached
selection, resolves basis/profile precedence and records the profile stamp.
`AnalysisSelection.load` owns graph loading, projection validation, power-model
scope, input limits and DVFS resolution.

These are intentionally two phases. Callers may reject resolved What-if settings
before graph loading. Fleet and exploration callers retain fatal profile errors
while recording graph failures per variant. They no longer construct a simulation
request and apply private preparation functions in the correct order themselves.

Throughput and CPU analysis policies stay with their callers. General simulation
keeps its own measured-replay and persistence behavior; analysis input selection
continues to reject measured replay. PostgreSQL remains the runtime authority.

## What-if baseline

Each request prepares and evaluates one baseline. Target discovery, interpretation
and candidate evaluation use that same resolved baseline. Legacy relative-clock
planning uses clocks already present in its target catalog (the same
`set_clock_mhz` values it previously recalculated).

A standalone preview keeps its previous contract: the resolved config is validated
as `WhatIfPreviewRequest`, the service-level timeline frame check is not applied
(the router still checks the requested frames), and the expected baseline hash is
compared before any timing evaluation.

This lifetime ends with the request. A separate preview or save resolves current
inputs again and checks the expected baseline hash. Candidate changes remain
detached; condition hashes include both baseline configuration and candidate
inputs. This is not a cross-request result cache.

## CPU analysis execution

`ui/src/lib/cpuAnalysis.ts` owns the calculation request, generation, results,
comparison, growth calculations and history. `useCpuAnalysis` connects that
module to React. The page retains input editing, selection and DSU display
experiments.

One run executes main, comparison, growth and comparison growth sequentially.
Two tokens keep the previous page semantics: the workflow token (former
`requestId`) is replaced by a new sweep/rebalance or `cancel`; the growth token
(former `sweepId`) is replaced by any growth start, a rebalance start or `reset`.
A standalone growth therefore does not cancel an in-flight rebalance; the
rebalance's own growth later supersedes it. The previous comparison stays visible
until the new main result arrives. A review snapshot uses the request associated
with the calculated growth result, never the currently edited inputs.

The production adapter uses existing HTTP calls and their admission/retry
behavior. Controlled test adapters exercise delayed responses and partial
failures through the same module interface. DOM tests retain page wiring and
user-facing behavior checks.

## Verification

The important observables are frozen snapshot content, selected measurement ID,
resolved input metadata and errors, What-if result/hash stability, and ownership
of CPU results and snapshot requests. Private helper call counts alone are not
sufficient. In particular, graph-loading fixtures that replace PostgreSQL and
What-if persistence fixtures that replace calculation test different concerns
from the real calculation and PostgreSQL suites.
