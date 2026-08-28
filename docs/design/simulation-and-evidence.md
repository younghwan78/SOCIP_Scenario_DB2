# Simulation and Evidence Architecture

| Field | Value |
| --- | --- |
| Status | Current |
| Last verified | 2026-08-26 |
| Primary code | `src/scenario_db/sim`, `models/evidence`, `comparison`, `reporting` |
| Primary tests | `tests/unit/sim`, `tests/unit/reporting`, `tests/unit/test_evidence_*` |

## 1. Evidence is the durable result boundary

Simulation and measurement share the `evidence` table and identity fields but keep kind-specific
details. The supported kinds are `evidence.simulation` and `evidence.measurement`. Every row is
scoped to a scenario and variant and carries execution context, aggregation, KPI, hash/lineage,
and optional breakdowns.

Evidence uses three compatible layers:

1. `kpi`: stable scenario-level headline metrics.
2. Typed detail fields such as IP/DMA/timing/DVFS, external devices, rail power, CPU and SW timing.
3. `metric_observations`: catalog-controlled values keyed by
   `metric_id + scope.kind + scope.ref`.

The metric catalog declares unit, valid scopes, comparison statistic, polarity, and optional
legacy KPI mapping. Import adapters normalize units; the comparison engine does not guess unit
conversions.

## 2. Simulation execution

The simulation adapter loads an effective canonical graph from PostgreSQL, applies variant
inheritance/routing/topology state, resolves capabilities and SoC profiles, then runs BW, power,
performance, DVFS, transfer, and timeline calculations. NetworkX and SimPy are required runtime
dependencies.

The API applies per-worker admission limits and request/graph size bounds before expensive work.
When capacity is full it returns `429` with `Retry-After`; it does not hold a worker indefinitely.
These controls are synchronous-process safeguards, not a durable distributed job queue.

The persisted `params_hash` supports result identity/cache decisions. Calculation trace is
optional debug evidence and should not be assumed present in every row.

## 3. Measurement normalization

Measurement import accepts reviewed summary inputs, including canonical sidecar metadata,
supported power CSV digests, and Perfetto-derived summaries. Raw traces, device identities,
credentials, and unredacted logs are not stored in the repository or PostgreSQL evidence payload.

Projection can derive a target-project prediction from calibrated source evidence while
preserving `derived_from` lineage and compatibility checks. A projected value is not a measured
value and must remain identifiable through evidence kind/context and provenance.

## 4. Prediction/measurement comparison

The comparison endpoint requires one simulation evidence row and one measurement evidence row.
Metric observations are aligned only when metric ID, scope, and canonical unit match. The catalog
selects the statistic and polarity used to interpret deltas. Missing coverage is reported; it is
not silently treated as zero or pass.

Scenario, variant, project, and execution context are part of comparison validity. Logical task
names are preferred over raw thread/process IDs for cross-build comparisons.

## 5. Report artifacts

Reporting projects stored simulation evidence into three HTML artifacts. A generation is written
to a unique staging directory, flushed, and atomically renamed before DB metadata is published.
Artifact metadata uses report-root-relative paths, checksum, byte length, MIME type, generation
ID, and timestamps; host absolute paths are not API or DB contract fields.

Reconciliation is dry-run by default and detects invalid paths, missing/checksum-mismatched files,
orphan HTML, and stale staging directories. Cleanup removes only explicitly safe stale staging
targets; missing, mismatched, and orphan files remain report-only for manual review.

## 6. Viewer and dashboard use

Evidence Dashboard queries persisted rows and renders kind-specific summaries. A requested
`sim_evidence_id` may overlay a view only when its scenario and variant match the requested graph.
The overlay augments view nodes, edges, and Level 0 resource rows; it does not alter the canonical
scenario definition.

## 7. Related contracts and guides

- [Measurement Evidence Contract](../contracts/data/measurement-evidence-contract.md)
- [Metric Observation Contract](../contracts/data/metric-observation-contract.md)
- [SoC Simulation Contract](../contracts/simulation/soc-simulation-contract.md)
- [Measurement Import Guide](../guides/measurement/measurement-import-guide-ko.md)
- [Prediction/Measurement Comparison Guide](../guides/comparison/prediction-measurement-comparison-guide-ko.md)
