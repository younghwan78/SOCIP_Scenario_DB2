# Write API Runbook

This runbook shows how to use the first Write API flow:

```text
stage -> validate -> diff -> apply
```

The current write scope supports:

- `scenario.variant_overlay`: one variant overlay.
- `scenario.pipeline_patch`: base scenario pipeline patch affecting every variant.
- `scenario.import_bundle`: canonical importer output staged before DB apply.

## Prerequisites

Run the API first:

```powershell
cd E:\50_Codex_Soc_Scenario_DB\implementation
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:5432/scenario_db"
uv run uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
```

Set a local API base variable in another PowerShell:

```powershell
$api="http://127.0.0.1:18000/api/v1"
```

## Happy Path

Use the valid variant overlay sample:

```powershell
$payload = Get-Content .\demo\write_payloads\variant_overlay_valid.json -Raw
$stage = Invoke-RestMethod -Method Post -Uri "$api/write/staging" -ContentType "application/json" -Body $payload
$stage
```

Expected result:

```json
{
  "batch_id": "...",
  "status": "staged",
  "target_id": "uc-camera-recording/FHD30-SDR-H265-runbook"
}
```

Validate:

```powershell
$batchId = $stage.batch_id
$validation = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/validate"
$validation
```

Expected result:

```json
{
  "batch_id": "...",
  "valid": true,
  "issues": []
}
```

Preview diff:

```powershell
$diff = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/diff"
$diff.changes | Format-Table field, change
```

Apply:

```powershell
$apply = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/apply"
$apply
```

Read the applied variant:

```powershell
Invoke-RestMethod "$api/scenarios/uc-camera-recording/variants/FHD30-SDR-H265-runbook"
```

Check the effective topology view:

```powershell
Invoke-RestMethod "$api/scenarios/uc-camera-recording/variants/FHD30-SDR-H265-runbook/view?level=0&mode=topology"
```

## Derived Variant Example

Use this when a variant should inherit most settings from an existing variant:

```powershell
$payload = Get-Content .\demo\write_payloads\variant_overlay_derived.json -Raw
$stage = Invoke-RestMethod -Method Post -Uri "$api/write/staging" -ContentType "application/json" -Body $payload
$batchId = $stage.batch_id
Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/validate"
Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/diff"
Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/apply"
```

The Read API returns the resolved projection:

```powershell
Invoke-RestMethod "$api/scenarios/uc-camera-recording/variants/UHD60-HDR10-H265-runbook-derived"
```

Expected resolved behavior:

- Parent fields from `UHD60-HDR10-H265` are inherited.
- `design_conditions_override.duration_category` is applied into `design_conditions`.
- `inheritance_chain` shows parent then child.
- `resolved` is `true`.

## Base Pipeline Patch Example

Use this only when the base scenario topology or buffer catalog needs to change.
Unlike a variant overlay, this affects every variant in the scenario.

```powershell
$payload = Get-Content .\demo\write_payloads\pipeline_patch_valid.json -Raw
$stage = Invoke-RestMethod -Method Post -Uri "$api/write/staging" -ContentType "application/json" -Body $payload
$batchId = $stage.batch_id
$validation = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/validate"
$diff = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/diff"
$diff.changes | Format-Table field, change
$diff.impact
```

Expected behavior:

- Validation returns `valid=true`.
- Diff target is the scenario ID, not a variant ID.
- `impact.variant_count` shows how many variants are affected by the base patch.
- `impact.blocking_variant_count` must be `0` before apply.

Apply:

```powershell
Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/apply"
Invoke-RestMethod "$api/scenarios/uc-camera-recording/variants/UHD60-HDR10-H265/graph"
```

The runtime graph should include the newly added base edge or buffer.

## Import Bundle Example

Use this after the legacy YAML importer has generated canonical documents. This
keeps importer output on the same review path as manually-authored writes:

```text
import -> stage -> validate -> diff -> apply
```

Build the staging payload from a generated canonical YAML directory:

```powershell
uv run python -m scenario_db.legacy_import.write_bundle `
  --generated generated\scenariodb `
  --out generated\scenariodb\import_bundle.json `
  --actor legacy-importer `
  --note "projectA legacy import" `
  --strict
```

The output JSON is a complete request body for `POST /api/v1/write/staging`.
For a quick smoke test, the repo also includes
`demo\write_payloads\import_bundle_valid.json`.

```powershell
$payload = Get-Content generated\scenariodb\import_bundle.json -Raw
$stage = Invoke-RestMethod -Method Post -Uri "$api/write/staging" -ContentType "application/json" -Body $payload
$batchId = $stage.batch_id
$validation = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/validate"
$validation.import_report
```

Expected behavior:

- Validation returns `valid=true`.
- `import_report.messages_by_level` summarizes importer warnings/errors.
- Any importer message with `level=error` makes validation fail.
- `target_id` is the imported scenario ID when the bundle contains a `scenario.usecase`.

Preview impact before apply:

```powershell
$diff = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/diff"
$diff.changes | Format-Table field, change
$diff.impact.scenario_impacts
```

The diff shows whether each canonical document is new or existing and whether
variants will be added, updated, or removed for each imported scenario.

Apply and read back:

```powershell
$apply = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/apply"
$apply.applied_refs
Invoke-RestMethod "$api/scenarios/uc-imported-camera-recording/variants/FHD30-Imported"
```

## Routing Switch Example

`routing_switch` disables existing base topology nodes or edges. It does not
modify the base scenario.

```json
"routing_switch": {
  "disabled_nodes": ["dpu"]
}
```

After apply:

```powershell
Invoke-RestMethod "$api/scenarios/uc-camera-recording/variants/FHD30-SDR-H265-runbook/graph"
```

The canonical graph summary should no longer include `ip-dpu-v9` for that
variant, and any edge touching `dpu` should be removed from the effective graph.

## SW Task Injection Example

`topology_patch` may inject SW task nodes. HW node injection is rejected.

```json
"topology_patch": {
  "remove_edges": [
    {"from": "isp0", "to": "mfc"}
  ],
  "add_nodes": [
    {"id": "sw_filter", "label": "SW Filter", "node_type": "SW", "layer": "kernel"}
  ],
  "add_edges": [
    {"from": "isp0", "to": "sw_filter", "type": "M2M", "buffer": "RECORD_BUF"},
    {"from": "sw_filter", "to": "mfc", "type": "control"}
  ]
}
```

This is intended for CPU/M2M task insertion. It is not a way to create new
physical HW paths.

## Failure Examples

### Unknown Edge

```powershell
$payload = Get-Content .\demo\write_payloads\variant_overlay_invalid_edge.json -Raw
$stage = Invoke-RestMethod -Method Post -Uri "$api/write/staging" -ContentType "application/json" -Body $payload
$validation = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$($stage.batch_id)/validate"
$validation.issues
```

Expected issue code:

```text
unknown_disabled_edge
```

### Unsupported Mode

```powershell
$payload = Get-Content .\demo\write_payloads\variant_overlay_invalid_mode.json -Raw
$stage = Invoke-RestMethod -Method Post -Uri "$api/write/staging" -ContentType "application/json" -Body $payload
$validation = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$($stage.batch_id)/validate"
$validation.issues
```

Expected issue code:

```text
unsupported_selected_mode
```

### Compression In Placement

```powershell
$payload = Get-Content .\demo\write_payloads\variant_overlay_invalid_placement.json -Raw
$stage = Invoke-RestMethod -Method Post -Uri "$api/write/staging" -ContentType "application/json" -Body $payload
$validation = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$($stage.batch_id)/validate"
$validation.issues
```

Expected issue code:

```text
compression_in_placement
```

Compression belongs to the buffer descriptor. LLC allocation belongs to
`placement`.

### Pipeline Patch Unknown Endpoint

```powershell
$payload = Get-Content .\demo\write_payloads\pipeline_patch_invalid_endpoint.json -Raw
$stage = Invoke-RestMethod -Method Post -Uri "$api/write/staging" -ContentType "application/json" -Body $payload
$validation = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$($stage.batch_id)/validate"
$validation.issues
```

Expected issue code:

```text
edge_target_not_found
```

### Pipeline Patch Invalid HW Edge

```powershell
$payload = Get-Content .\demo\write_payloads\pipeline_patch_invalid_otf.json -Raw
$stage = Invoke-RestMethod -Method Post -Uri "$api/write/staging" -ContentType "application/json" -Body $payload
$validation = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$($stage.batch_id)/validate"
$validation.issues
```

Expected issue codes:

```text
otf_edge_must_not_have_buffer
physical_edge_endpoint_invalid
```

`vOTF` is different from `OTF`: it must declare a buffer because the connection
is modeled as a low-latency line-buffer path. If the buffer is LLC-backed, record
that in the buffer descriptor or variant `buffer_overrides.placement`.

### Import Bundle Missing Buffer

```powershell
$payload = Get-Content .\demo\write_payloads\import_bundle_valid.json -Raw | ConvertFrom-Json
$payload.payload.documents[0].pipeline.edges += @{
  from="isp0"; to="mfc"; type="M2M"; buffer="MISSING_BUF"
}
$stage = Invoke-RestMethod -Method Post -Uri "$api/write/staging" -ContentType "application/json" -Body ($payload | ConvertTo-Json -Depth 30)
$validation = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$($stage.batch_id)/validate"
$validation.issues
```

Expected issue code:

```text
import_edge_buffer_not_found
```

## Response Interpretation

`GET /api/v1/write/staging/{batch_id}` returns the audit state:

- `status=staged`: payload stored only.
- `status=validated`: validation passed.
- `status=validation_failed`: validation returned business-rule errors.
- `status=diff_ready`: diff is available.
- `status=applied`: canonical variant row was created or updated.

Business-rule validation failures return HTTP `200` with `valid=false`. This is
intentional so UI clients can show all issues in one response. Malformed HTTP
requests still use the normal API error contract.
