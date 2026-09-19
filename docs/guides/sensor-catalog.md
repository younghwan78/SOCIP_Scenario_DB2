# Reusable sensor catalog and readout timing

Sensor data has three layers:

- `sensor.catalog`: board-specific DT mode/VC/wiring declarations. Full mode labels, including suffixes, are retained in a JSONB document.
- `sensor.board_lineup`: board configurations and installed sensor alternatives. An orphan catalog is searchable but cannot be selected as installed.
- `sensor.timing_profile`: sensor/CIS revision-specific readout parameters, independent of any SoC or project. These can be reused by future projects.

Migration `0019` adds these tables and `project_sensor_selections`. Selections point to the source board configuration; they do not assert electrical compatibility with a target board. A new board should import its own catalog/lineup while reusing the verified CIS timing profile. Catalog IDs must remain globally unique; use a new ID for a distinct source revision that must coexist.

## Import

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scenario_db.etl.loader db_fixtures_Exynos2600_S26Plus --strict --report-json runtime_logs/sensor-import.json
```

The existing ETL CLI imports all three kinds, validates mode counts and lineup references, and rolls back the batch on strict errors. Reimport of an identical hash is unchanged. An updated catalog replaces its document, so review removed modes before import. Existing scenario profiling/evidence and 14 extra camera recording variants are preserved by the selective fixture merge.

## VVALID and CSIS frame window

For a verified CIS mode:

```
line_time_s = line_length_pck / pixel_clock_hz
valid_time_ms = line_time_s * readout_lines * 1000
frame_period_ms = line_time_s * frame_length_lines * 1000
vertical_blank_ms = frame_period_ms - valid_time_ms
```

`readout_lines` defaults to `active_height` for a single image readout. Multi-exposure/interleaved modes require the actual readout line count for the selected sequence. The computed VVALID predicts the CSIS Frame Start–Frame End window; it is not an observed timing measurement. Exposure time, frame period and MIPI payload transfer lower bounds are different quantities.

The calculator rejects nonfinite/nonpositive timing inputs and readout longer than the frame. DT FPS/MIPI rate alone returns `missing_timing`; simulator display and clock correction no longer substitute frame period for VVALID. DT `vvalid_time`/`req_vvalid_time` are preserved as metadata but not automatically interpreted without validated units and semantics.

The supplied GNG profile contains 47 CIS modes. Example `cis_4sum_ln1_raw10_4080x3060_120fps_3993msps`: 3,532,800,000 Hz, 8,880 clocks/line, 3,312 frame lines, 3,060 image lines gives **7.691576 ms VVALID**. Twenty basic GNG DT modes now have reviewed mode-index bindings to these CIS modes. The other 429 remain unbound. Matching dimensions/FPS is insufficient to identify LN/DCG/AEB behavior.

## API and UI

- `GET /api/v1/sensors/catalogs?board=m2s`
- `GET /api/v1/sensors/catalogs/{id}`
- `GET /api/v1/sensors/catalogs/{id}/modes/{full_label}/timing`
- `GET /api/v1/sensors/lineups`
- `GET /api/v1/sensors/timing-profiles?sensor_name=S5KGNG`
- `GET /api/v1/sensors/timing-profiles/{id}/modes/{cis_label}`
- `POST /api/v1/sensors/timing/calculate`: read-only calculation from unit-explicit timing inputs.
- `POST /api/v1/sensors/selections`: writer/admin selection of an installed sensor; project, catalog, lineup, slot and board configuration must exist.
- `GET /api/v1/sensors/selections?project_ref=...`

The **Sensor Catalog** Streamlit page shows DT mode/VC/wiring, calculated timing for bound modes, missing mapping reasons and separate CIS profile calculations. It exports a simulation config fragment:

```json
{
  "sensor_readout": {
    "sensor_rear": {
      "active_width": 4080,
      "active_height": 3060,
      "pixel_clock_hz": 3532800000,
      "line_length_pck": 8880,
      "frame_length_lines": 3312,
      "source": {"basis": "verified CIS mode"}
    }
  }
}
```

Merge this fragment into the simulation request `config`. The actual profile export includes profile ID/hash/revision and CIS label in `source`. This is an explicit exploration assumption; node dimensions must agree, and it cannot modify measured replay. It changes sensor source timing/CSIS window and sensor OTF clock correction without writing back to the catalog. No automatic DT-to-CIS equivalence is claimed.

## Noncamera import boundary

Eight noncamera scenarios (74 variants) now contain producer BW/DVFS/provenance and assumed SW timing. UFS/ABOX/M2M scaler replace CPU placeholders. Existing executable camera models and versioned IPs remain intact. Disabled nodes are removed from simulation inputs; a node with explicit SW timing does not also create a pixel HW workload.

`model_ref` and source `bw_model`/`dvfs_model` formulas remain reference metadata, not executable code. Existing readiness checks identify missing PPC/power models and adapter warnings identify unevaluated source formulas. Import success is not a calibrated noncamera power/clock prediction. Typed audio/byte-domain execution models require separate validated unit/model contracts; DPU BTS votes must not be substituted for surface traffic.

The next calculation stage is now available in [Driver Models](driver-models.md): UFS/ABOX/MSCL/DPU have versioned typed endpoint calculations, with explicit aggregation and power limits.


## DT transport report

`GET /api/v1/sensors/catalogs/{id}/modes/{full_label}/transport` provides
`sensor-transport-v1`, the board/catalog hash, input snapshot and per-route VC rows.
The Sensor Catalog page displays this report and exports JSON.

- Packed payload = width × height × bits_per_pixel / 8. Empty DATA_NONE routes are ignored.
- Identical incoming map/format/size declarations routed to multiple DMA outputs count once on the wire. Conflicting declarations return missing_input.
- Link capacity follows the imported producer's `is-hw-dvfs.c get_mbps`: lanes × rate × 16/7 for CPHY, lanes × rate for DPHY. The analytical result retains fractional Mbps instead of the driver's integer truncation.
- The rate assumption is DT fps capped by a positive option.max_fps when present. This is a declared operating point, not measured cadence.
- Single-image reports assume every unique VC repeats at that rate. Multiple image VC, AEB and DCG return cadence_unresolved: all_vcs_at_assumed_fps_bytes_s is diagnostic only and csis_payload_bytes_s stays null.
- Payload utilization excludes packet overhead, blanking and burst scheduling. payload_within_capacity is a necessary payload check, not a guarantee of feasibility.
- DRAM traffic remains unknown until routing, packing/stride, compression and vOTF are specified. This report does not change aggregate simulation bandwidth.
- Transfer lower bounds are not VVALID. Reviewed basic GNG DT-to-CIS bindings provide Valid Time separately; the independent CIS calculator also remains available.


## Pinned scenario sensor binding

The Sensor Catalog page now prepares a binding with **Scenario sensor binding**.
Choose an installed source configuration/slot and provide the target scenario,
variant and sensor node. Downloaded JSON is a fragment to merge into simulation
`config`; it is not a complete simulation request.

`POST /api/v1/sensors/projection/prepare` accepts `scenario_id`, `variant_id`,
`node_id`, `catalog_ref`, full `mode_label`, `lineup_ref`, `board_config`, `slot`.
It resolves the source and returns `config.sensor_modes`, projected external
devices and warnings without writing DB. Each binding pins catalog and lineup
hashes. `/simulation/run` revalidates those hashes and installation on every run.
A changed source requires preparing a new binding.

The first supported scope is a single-image mode on an active node of the same
sensor, with the same sensor dimensions and bit depth as the existing pipeline.
The scenario rate must be within the DT/max_fps cap and the payload must fit the
source link. Payload is recomputed at scenario FPS. Existing crop, DMA packing,
compression and output transforms remain the scenario's explicit policies.
Changing dimensions/format requires an explicit pipeline update first. Multiple
image/AEB/DCG cadence is rejected until its scheduling contract is known.

The selected DT mode, source wiring rate, VC report and source snapshot are
included in `external_devices`, simulation hashes and persisted evidence.
Execution method is `projection`. This validates source-board installation, not
electrical compatibility with a future target board. The original catalog,
scenario and sensor IP are not mutated.

Old CIS timing is cleared when a new DT mode is selected, then a reviewed timing binding is applied when present. A manual CIS readout override on the same bound node is rejected; measured replay also rejects DT bindings.
`external_devices.transport` is CSIS payload, not DRAM traffic, and is not added
to aggregate DMA/power totals. No VVALID is inferred from payload or FPS.


## Reviewed DT-to-CIS timing bindings

GNG m1s/m2s now include 20 basic DT mode bindings (10 per board): mode0,
mode3, mode11, mode14, mode20, mode22, mode28, mode44, mode45 and mode46.
These follow the driver dispatch `cfg.mode -> mode_infos[index]`, not a
resolution/FPS search. The source assumptions are setA at 19.2 MHz, non-mirror,
and no runtime seamless transition. Source file paths, hashes and line references
are retained. AEB/DCG, NFI, LN and remosaic suffixes remain unmapped pending
an explicit runtime sequence contract. Other sensors still need CIS profiles.

Each `modes.<full_label>.timing_binding` contains the profile ID/revision, CIS
mode label, DT mode index, canonical timing-input SHA256 and source evidence.
Strict ETL validates profile identity, revision, timing hash, mode index and
readout dimensions; a profile-only update that invalidates a binding rolls back.
No additional table or migration is required: catalog JSONB holds the reference,
and reusable timing inputs remain in the independent timing profile.

The existing `/catalogs/{id}/modes/{label}/timing` API now returns calculated
VVALID and resolved inputs for bound modes. `binding_status` distinguishes
verified_mode_index, unmapped and invalid. Sensor Catalog displays the calculated
window above the DT details. A changed/missing profile gives invalid_binding,
not a stale cached value.

Simulation sensor bindings apply this calculated readout automatically, clear
unrelated old timing and retain the scenario FPS. Thus a 120fps setfile can supply
its line/readout time to a 30fps exploration without forcing 120fps release cadence.
The sensor valid window must fit the scenario period. This assumes fixed line
readout and adjusted frame blanking, not a runtime switch to another LN mode.
The timing source/profile hash participates in simulation evidence and input hash.
An additional manual sensor_readout on the same bound node is still rejected to
avoid overriding the verified mapping. No transport traffic is added to DRAM totals.

Reproduce the source review/import enrichment with:

```powershell
.\.venv\Scripts\python.exe scripts/bind_gng_cis_timing.py --source-root <kernel-workspace-root>
```

The script checks all 47 imported timing entries against setA, verifies both DT
source hashes, adds only basic full labels, and reads the source tree without
changing it. The remaining 429 DT modes are still unbound.

Timeline events retain the exact readout in `v_valid_ms`. Existing OTF group reservation bars can be longer when downstream processing dominates; their full reservation duration is not a new sensor readout measurement.
