# Metric Observation Contract

`metric_observations` is the extensible, comparison-oriented metric layer shared
by `evidence.simulation` and `evidence.measurement`. Existing `kpi`,
`vdd_power`, `dma_breakdown`, `timing_breakdown`, and `sw_task_timing` fields
remain supported for compatibility and specialized views.

## Shape

```yaml
metric_observations:
  - metric_id: sw.start_jitter
    scope: {kind: task, ref: eis_warp}
    unit: us
    stats: {mean: 84, p95: 210, max: 620, n: 5400}
```

Each observation must contain:

- a cataloged `metric_id`;
- one allowed `scope.kind` and a non-empty logical `scope.ref`;
- the catalog's canonical `unit`;
- exactly one of `value` or `stats`.

The identity used for prediction/measurement joins is:

```text
metric_id + scope.kind + scope.ref
```

Duplicate identities in one evidence document are invalid.

## Comparison semantics

Prediction and measurement observations join on the identity above. The
catalog's `compare_statistic` selects the measured statistic; a prediction
`value` remains a scalar. Delta is always:

```text
prediction - measurement
```

Comparison rows use explicit coverage states instead of silently dropping
unmatched data:

- `MATCHED`
- `PREDICTION_ONLY`
- `MEASUREMENT_ONLY`
- `UNIT_MISMATCH`
- `STATISTIC_MISSING`
- `CONTEXT_MISMATCH`

Project/scenario/variant and SW baseline/thermal/power-state mismatches are
blocking: values remain visible but delta is not calculated. Silicon revision
and ambient temperature mismatches are advisory because pre-silicon projection
is commonly checked against later silicon.

## Catalog

The default catalog is
`src/scenario_db/models/evidence/metric_catalog.yaml`. Add a catalog entry when
a new metric is introduced. Adding a metric does not require a database
migration, but changing the meaning or canonical unit of an existing metric is
a contract change and requires migration/reconciliation of stored evidence.

Raw log adapters must normalize source units into the catalog's canonical unit
before generating evidence. The comparison layer does not guess whether, for
example, `GB/s` means decimal or binary bandwidth.

PMU-derived metrics (`clock.ip`, `clock.ip_dominant`, `bandwidth.mem_read`,
`bandwidth.mem_write`, `cpu.cycles`, `cpu.instructions`, `cpu.ipc`) are produced by
`meas_import/pmu_digest.py` from a neutral sample format; see the Measurement
Import Guide section 4.4.1. On the prediction side `clock.ip` comes from
`dvfs_breakdown` (max set clock per IP ref) and `bandwidth.mem_*` from
`dma_breakdown` totals under scope `mif/total`.

## Compatibility policy

- Common scenario KPIs stay in `kpi` for headline queries and gates.
- Existing typed detail fields remain the source for legacy evidence.
- Importers may emit equivalent observations for detailed comparison.
- New metric families should start in the catalog and observation layer rather
  than adding new top-level evidence fields.
