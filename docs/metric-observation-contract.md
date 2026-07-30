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

## Catalog

The default catalog is
`src/scenario_db/models/evidence/metric_catalog.yaml`. Add a catalog entry when
a new metric is introduced. Adding a metric does not require a database
migration, but changing the meaning or canonical unit of an existing metric is
a contract change and requires migration/reconciliation of stored evidence.

Raw log adapters must normalize source units into the catalog's canonical unit
before generating evidence. The comparison layer does not guess whether, for
example, `GB/s` means decimal or binary bandwidth.

## Compatibility policy

- Common scenario KPIs stay in `kpi` for headline queries and gates.
- Existing typed detail fields remain the source for legacy evidence.
- Importers may emit equivalent observations for detailed comparison.
- New metric families should start in the catalog and observation layer rather
  than adding new top-level evidence fields.
