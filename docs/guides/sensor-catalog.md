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

The supplied GNG profile contains 47 CIS modes. Example `cis_4sum_ln1_raw10_4080x3060_120fps_3993msps`: 3,532,800,000 Hz, 8,880 clocks/line, 3,312 frame lines, 3,060 image lines gives **7.691576 ms VVALID**. The 449 DT catalog modes are not automatically mapped to these 47 CIS modes. Matching dimensions/FPS is insufficient to identify LN/DCG/AEB behavior.

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

The **Sensor Catalog** Streamlit page shows DT mode/VC/wiring, missing timing inputs and separate CIS profile calculations. It exports a simulation config fragment:

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
