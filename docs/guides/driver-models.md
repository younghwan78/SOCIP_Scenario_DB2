# Noncamera driver model calculations

`noncamera-driver-v1` evaluates reviewed S5E9965 UFS, ABOX, MSCL and DPU models. YAML formulas remain text: no `eval`, generated code or arbitrary model execution. Dispatch is restricted to the four imported IP IDs; another SoC requires a reviewed model registration.

## Supported outputs and units

| Model | Calculation | Clock / DVFS | Boundary |
|---|---|---|---|
| UFS | bitrate Mbps × 1,000,000 / 8 → bytes/s | Unknown | A storage read is a DRAM write; consumer reads belong to the consumer |
| ABOX | sample rate × channels × bytes/sample × stream count | Validate selected AUD operating point | Offload PCM demand is known, actual SRAM refill traffic remains null |
| MSCL | Source/destination surfaces × bpp × fps | max(src pixels,dst pixels) × fps / explicit PPC row; lowest sufficient QoS row | Rotation chooses rotated PPC; compression ratio and vOTF are explicit inputs |
| DPU | Sum of scanned surface bytes; separate BTS vote | Resolution clock / declared PPC; lowest sufficient DISP level | Unrotated/uncompressed layers; no RCD, bus/customer overhead or writeback |

Canonical traffic is **bytes/s**. UFS source `KB/s` uses 1000; audio/scaler source `KB/s` uses 1024 and is reported as `KiB/s`. DPU BTS vote derives from kHz × bytes and is reported separately as kB/s. These are not interchangeable. Scaler MIF reference BW scaling is deferred until its reference-unit contract is validated.

DPU's 60 Hz vote floor does not force surface traffic to 60 Hz: 30 and 60 Hz can have the same BTS vote while traffic doubles. GPU/M2M fallback uses the explicitly declared resulting DPU layers; upstream composition traffic is not counted as DPU traffic.

No core power coefficient is invented. `power_mw: null` / `power_status: uncalibrated` is intentional. Exceeding every QoS level produces `infeasible`, not a successful clamp to the maximum.

## API / exploration

- `GET /api/v1/driver-models?scenario_id=...&variant_id=...`
- `POST /api/v1/driver-models/explore` with `scenario_id`, `variant_id`, and `overrides` keyed by active node ID.
- Overrides use full typed inputs from a report row, including the `model` discriminator (`ufs`, `abox`, `mscl`, `dpu`). Unknown fields and nonfinite/invalid dimensions/rates are rejected.
- Missing fixture bitrate is `missing_input`, not zero. Fill the explicit bitrate in an exploration override when a defensible value is available.

The **Driver Models** Streamlit page supports baseline inspection and JSON input exploration. It does not modify fixtures or DB.

Simulation accepts the same overrides in `config.driver_model_overrides`. The result and persisted evidence expose `calculation_trace.driver_models` even when debug trace is disabled. The report includes version, input snapshot, fixture provenance and IP catalog SHA; these also participate in the simulation parameter hash. Overrides affect this driver calculation report only, not the legacy pixel model workloads.

## Aggregation boundary

Per-endpoint BW estimates are **not added** to legacy DMA/power totals: those transfers may already represent the same bytes. DPU vote is not energy traffic. Before replacing aggregate totals, define ownership per transfer and reconcile source tables, codec traffic and upstream composition. MFC/APV/GPU/NPU driver formulas remain outside v1. Legacy simulation readiness can remain blocked for a missing executable pixel/power model despite a calculated driver BW report.

The source scalar/array inputs may themselves be assumptions. `input_basis`, `input_provenance`, `design_conditions` and source metadata preserve this distinction; calculated does not mean measured.
