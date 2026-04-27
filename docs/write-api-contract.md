# Write API Contract

This document defines the first write-side contract after the Read API freeze.

## Scope

The first Write API target is intentionally narrow:

- Supported: `scenario.variant_overlay`
- Deferred: full `scenario.usecase` replacement, capability catalog write, evidence write, issue/waiver write, YAML export.

The goal is to let users add or modify scenario variants without breaking the
canonical base topology or the existing Read API/viewer contract.

## Authoring Model

Scenario authoring is split into two layers.

| Layer | Source Of Truth | Write Rule |
| --- | --- | --- |
| Base scenario | `scenarios.pipeline` | Defines the superset HW/SW/memory topology. |
| Variant overlay | `scenario_variants.*` overlay fields | Selects conditions, routes, modes, buffers, and requirements for one variant. |

The base scenario should contain the physically possible topology. A variant
must not create new HW-to-HW routes that are absent from the base topology.

## Variant Overlay Fields

The canonical variant record stores these authoring fields:

- `design_conditions`: identity-level scenario axes such as resolution, fps, codec, hdr, concurrency.
- `design_conditions_override`: child-only design condition delta for `derived_from_variant`.
- `size_overrides`: variant-specific size anchors such as `record_out` and `preview_out`.
- `routing_switch`: `disabled_edges` and `disabled_nodes` over the base topology.
- `topology_patch`: limited patch used only for SW task injection or removing existing base edges.
- `node_configs`: per-node mode, operation, port, clock, DMA, or SYSMMU settings.
- `buffer_overrides`: per-buffer format, bitdepth, compression, alignment, and placement changes.
- `ip_requirements`: IP-level requirements used by resolver/review gate.
- `sw_requirements`: SW profile, HAL, firmware, and feature requirements.
- `violation_policy`: review gate behavior for the variant.

`design_conditions` is not execution context. Run-specific fields such as
silicon revision, SW baseline, build ID, measured timestamp, and tool provenance
belong in evidence or review records.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/write/staging` | Store a candidate write batch without changing canonical data. |
| `GET /api/v1/write/staging/{batch_id}` | Inspect a staged batch and its latest validation/diff/apply status. |
| `POST /api/v1/write/staging/{batch_id}/validate` | Validate schema and topology constraints. |
| `POST /api/v1/write/staging/{batch_id}/diff` | Preview canonical changes before apply. |
| `POST /api/v1/write/staging/{batch_id}/apply` | Apply a validated batch to canonical tables. |

## Request Shape

```json
{
  "kind": "scenario.variant_overlay",
  "actor": "architect@example.com",
  "note": "Add UHD60 HDR10 recording variant",
  "payload": {
    "scenario_ref": "uc-camera-recording",
    "variant": {
      "id": "UHD60-HDR10-H265",
      "severity": "heavy",
      "design_conditions": {
        "resolution": "UHD",
        "fps": 60,
        "codec": "H.265",
        "hdr": "HDR10",
        "concurrency": "with_preview"
      },
      "size_overrides": {
        "record_out": "3840x2160",
        "preview_out": "1920x1080"
      },
      "routing_switch": {
        "disabled_edges": [],
        "disabled_nodes": []
      },
      "node_configs": {
        "mfc": {
          "selected_mode": "high_throughput",
          "target_clock_mhz": 400
        }
      },
      "buffer_overrides": {
        "RECORD_BUF": {
          "format": "YUV420",
          "compression": "SBWC_v4",
          "placement": {
            "llc_allocated": true,
            "llc_allocation_mb": 1,
            "llc_policy": "dedicated",
            "allocation_owner": "MFC"
          }
        }
      }
    }
  }
}
```

## Validation Rules

- `kind` must be `scenario.variant_overlay`.
- `payload.scenario_ref` must reference an existing scenario.
- `payload.variant.id` must be present.
- `derived_from_variant`, when present, must reference an existing variant in the same scenario.
- `routing_switch.disabled_nodes` must reference base pipeline node IDs.
- `routing_switch.disabled_edges` must reference existing base edges by `id` or by `from`/`to`.
- `topology_patch.remove_edges` must reference existing base edges.
- `topology_patch.add_nodes` may only add SW task nodes.
- `topology_patch.add_edges` must touch at least one injected SW task node.
- `node_configs` must reference base nodes or injected SW task nodes.
- `node_configs.*.selected_mode`, when present, must exist in the referenced IP capability `operating_modes`.
- `buffer_overrides` must reference existing scenario buffers.
- Compression and LLC placement must remain separate fields.

Validation returns `200` with `valid=false` for business-rule failures. Malformed
HTTP requests still return the standard API error contract.

## Apply Semantics

`apply` is idempotent for the same latest staged payload:

- Existing variant: update overlay fields in place.
- New variant: insert a new `scenario_variants` row.
- Batch status becomes `applied`.
- Write events record stage, validate, diff, and apply actions for audit.

Canonical data is changed only by `apply`; `stage`, `validate`, and `diff` never
modify scenario or variant records.

## Read Projection Semantics

After apply, Read API and viewer projections resolve the variant overlay into an
effective topology:

- Disabled nodes are removed with all touching edges.
- Disabled or removed edges are filtered from the base topology.
- SW task injection nodes and edges are appended if their endpoints remain valid.
- Base scenario topology remains unchanged; the effective graph is a read-time projection.
