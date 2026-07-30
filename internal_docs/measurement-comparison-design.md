# Measurement Comparison Internal Design

## 1. Purpose and boundary

This design supports internal camera-scenario prediction/measurement comparison
without requiring the complete future measurement field set to be known in
advance.

Repository fixtures remain synthetic/public-safe. Real project identifiers,
device identities, ACLs, storage URLs, raw traces, power logs, and credentials
must be supplied only in the internal deployment environment.

The first intended camera matrix is:

- FHD30 recording
- FHD60 recording
- UHD30 recording
- UHD60 recording
- 8K30 recording

Project/scenario identity and the exact variant conditions are internal inputs
and are not established by this change.

## 2. Data architecture

Evidence keeps three compatible layers:

1. `kpi`: stable scenario-level metrics used by headline queries and gates.
2. Existing typed details: `vdd_power`, `dma_breakdown`,
   `timing_breakdown`, `sw_task_timing`, and related specialized views.
3. `metric_observations`: catalog-controlled comparison records identified by:

   ```text
   metric_id + scope.kind + scope.ref
   ```

The observation layer is stored in one optional PostgreSQL JSONB column. Adding
a new metric catalog entry does not require another database migration.

Each observation has exactly one value shape:

- `value`: calculated/scalar value; or
- `stats`: measured distribution digest such as mean/p95/std/n.

Raw measurement artifacts remain outside PostgreSQL. Evidence stores artifact
pointers and integrity metadata only.

## 3. Metric catalog policy

The default catalog is:

```text
src/scenario_db/models/evidence/metric_catalog.yaml
```

Every metric entry defines:

- category;
- allowed scope kinds;
- canonical unit;
- comparison statistic;
- polarity;
- optional legacy KPI key.

Rules:

- Add a catalog entry rather than adding a new top-level evidence field.
- Never change an existing metric's meaning or canonical unit in place.
- Normalize source units in the adapter/import stage.
- Do not make the comparison engine guess unit conversion semantics.
- Use logical task names instead of raw process/thread names as cross-build
  comparison keys.

## 4. Import paths

### 4.1 Canonical YAML

The supported initial internal handoff is a `meta.yaml` sidecar that can carry:

- KPI-only values;
- explicit `metric_observations`;
- a power CSV specification;
- a Perfetto trace specification; or
- a combination of these.

`scenario_db.meas_import` generates validated `evidence.measurement` YAML.
Explicit observations win when the same identity would also be generated from
a legacy digest.

### 4.2 Source adapters

Source-specific adapters must terminate at the canonical YAML contract:

```text
Power/BW/camera/Perfetto log
  -> source adapter
  -> canonical measurement YAML
  -> schema/catalog validation
  -> direct ETL
  -> PostgreSQL
```

The comparison service must not parse raw logs.

Implement adapters only after the internal source format and measurement
semantics are confirmed. Each adapter requires synthetic fixtures for:

- valid input;
- missing required columns/events;
- unit normalization;
- duplicate samples;
- incomplete runs;
- deterministic output.

## 5. Comparison semantics

The canonical endpoint is:

```text
GET /api/v1/compare/prediction-measurement
  ?prediction_id=<simulation evidence id>
  &measurement_id=<measurement evidence id>
```

The comparison layer normalizes both explicit observations and legacy KPI/detail
fields. It returns every identity found on either side.

Statuses:

- `MATCHED`
- `PREDICTION_ONLY`
- `MEASUREMENT_ONLY`
- `UNIT_MISMATCH`
- `STATISTIC_MISSING`
- `CONTEXT_MISMATCH`

Delta semantics:

```text
delta = prediction - catalog-selected measurement statistic
delta_pct = delta / measurement * 100
```

Missing metrics are coverage results, not zero values.

## 6. Context policy

The following mismatches block delta calculation:

- project;
- scenario;
- variant;
- SW baseline;
- thermal state;
- power state.

Values remain visible, but comparison rows are marked `CONTEXT_MISMATCH`.

Silicon revision and ambient temperature are advisory. This permits an explicit
pre-silicon prediction to be inspected against later silicon without silently
claiming that the execution contexts are identical.

Missing legacy context is reported but does not automatically block. Internal
production data should treat missing required context as an ingest quality
failure before it reaches comparison.

## 7. Dashboard behavior

The measurement view has a `Metrics` tab that shows canonical observations,
including normalized legacy values.

Prediction-vs-measurement comparison shows:

- catalog-selected headline KPI values;
- context mismatch details;
- matched/prediction-only/measurement-only/blocked counts;
- all scoped metric rows for rail, DMA port, pipeline stage, task, and thread.

Specialized Power and SW Timing tabs remain available and are not replaced by
the generic observation table.

## 8. Internal rollout order

1. Confirm internal project/scenario/variant identity.
2. Register any additional metric definitions and units in the catalog.
3. Apply Alembic revision `0014`.
4. Deploy API and Dashboard from the same revision.
5. Generate synthetic canonical evidence using the intended internal meta
   shape.
6. Run strict import and direct ETL validation.
7. Verify comparison coverage for all five camera variants.
8. Confirm context mismatches suppress delta.
9. Connect one real internal source adapter in the internal environment.
10. Review artifacts, access control, retention, and backup policy before bulk
    import.

## 9. Acceptance checks

For each of the five variants:

- prediction and measurement resolve to the same project/scenario/variant;
- required context is present;
- total power, total BW, frame latency, and effective FPS appear as scenario
  metrics;
- expected rail identities appear;
- expected DMA/path metrics appear or are explicitly `*_ONLY`;
- expected logical SW tasks appear;
- jitter metrics use the catalog unit and selected statistic;
- no unit or statistic mismatch is hidden;
- raw artifact pointers are valid and integrity metadata is available;
- a reviewer can explain every displayed delta from the source evidence.

## 10. Deferred internal decisions

The following are intentionally not guessed in the repository:

- real project and board identifiers;
- exact camera mode conditions and naming;
- authoritative rail/domain mapping;
- BW monitor log schema;
- camera latency event definitions;
- runtime versus start-time jitter definitions;
- pass/warn/fail thresholds;
- internal artifact storage and retention;
- SSO roles and data ACLs.
