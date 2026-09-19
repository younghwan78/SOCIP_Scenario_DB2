"""Versioned, unit-explicit noncamera driver calculators; never evaluate YAML code."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from pydantic import ConfigDict, Field, TypeAdapter, ValidationError
from scenario_db.models.common import BaseScenarioModel

Positive = Annotated[float, Field(gt=0, le=1e12, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, le=1e12, allow_inf_nan=False)]
Size = tuple[Annotated[int, Field(gt=0, le=1000000)], Annotated[int, Field(gt=0, le=1000000)]]


class Input(BaseScenarioModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class StorageInput(Input):
    model: Literal["ufs"] = "ufs"
    bitrate_mbps: Nonnegative
    operation: Literal["read", "write"] = "read"


class AudioInput(Input):
    model: Literal["abox"] = "abox"
    sample_rate_khz: Positive
    bit_depth: Literal[16, 24, 32]
    channels: int = Field(gt=0, le=1024)
    playback_streams: int = Field(ge=0, le=1024)
    capture_streams: int = Field(ge=0, le=1024)
    offload: bool
    aud_freq_khz: Positive | None = None


class ScalerInput(Input):
    model: Literal["mscl"] = "mscl"
    src: Size
    dst: Size
    fps: Positive
    src_bpp: Positive
    dst_bpp: Positive
    ppc_row: str
    rotated: bool = False
    votf: bool = False
    compression_ratio: float = Field(default=1, gt=0, le=1)


class Layer(Input):
    src: Size
    dst: Size
    bpp: Positive


class DisplayInput(Input):
    model: Literal["dpu"] = "dpu"
    panel_width: int = Field(gt=0, le=1000000)
    panel_height: int = Field(gt=0, le=1000000)
    refresh_hz: Positive
    layers: list[Layer] = Field(min_length=1, max_length=128)
    dsc_slice_count: int = Field(ge=0, le=128)


DriverInput = Annotated[
    StorageInput | AudioInput | ScalerInput | DisplayInput, Field(discriminator="model")
]
INPUT = TypeAdapter(DriverInput)
MODELS = {"ufs": StorageInput, "abox": AudioInput, "mscl": ScalerInput, "dpu": DisplayInput}
GROUPS = {"UFS": "ufs", "ABOX": "abox", "MSCL": "mscl", "DPU": "dpu"}
VERSION = "noncamera-driver-v1"
SUPPORTED_IPS = {"ip-ufs-s5e9965", "ip-abox-s5e9965", "ip-m2m-scaler-s5e9965", "ip-dpu-s5e9965"}
POSITIVE = TypeAdapter(Positive)


def evaluate(raw: dict[str, Any], caps: dict[str, Any]) -> dict[str, Any]:
    data = INPUT.validate_python(raw)
    out: dict[str, Any] = {
        "model": data.model,
        "version": VERSION,
        "status": "calculated",
        "inputs": data.model_dump(mode="json"),
        "power_mw": None,
        "power_status": "uncalibrated",
        "notes": [],
        "source": {k: caps[k] for k in ("bw_model", "perf_model", "dvfs_model") if k in caps},
    }
    if isinstance(data, StorageInput):
        rate = data.bitrate_mbps * 1_000_000 / 8
        # Storage read produces a DRAM write. Consumer DRAM read is a separate owner.
        out.update(
            read_bytes_s=rate if data.operation == "write" else 0,
            write_bytes_s=rate if data.operation == "read" else 0,
            storage_payload_bytes_s=rate,
            source_kB_s=rate / 1000,
        )
        out["notes"].append(
            "Host storage endpoint only; consumer access must not be counted here again."
        )
    elif isinstance(data, AudioInput):
        stream = data.sample_rate_khz * 1000 * data.channels * data.bit_depth / 8
        read, write = stream * data.playback_streams, stream * data.capture_streams
        out.update(
            pcm_read_bytes_s=read,
            pcm_write_bytes_s=write,
            read_bytes_s=None if data.offload else read,
            write_bytes_s=None if data.offload else write,
            source_KiB_s=(read + write) / 1024,
        )
        if data.offload:
            out["status"] = "partial"
            out["notes"].append(
                "PCM stream demand is calculated; offload SRAM refill traffic requires a measured duty/transfer model."
            )
        levels = (caps.get("dvfs_model") or {}).get("aud_qos_levels_khz", [])
        if data.aud_freq_khz is not None:
            if data.aud_freq_khz not in levels:
                raise ValueError("AUD frequency is not a declared operating point")
            out["selected_aud_freq_khz"] = data.aud_freq_khz
        out["notes"].append(
            "AUD frequency is a selected operating point, not predicted from PCM rate."
        )
    elif isinstance(data, ScalerInput):
        perf = caps.get("perf_model") or {}
        rows = [r for r in perf.get("ppc_table", []) if r["format"] == data.ppc_row]
        if len(rows) != 1:
            raise ValueError("Scaler PPC row must identify exactly one format entry")
        ppc = POSITIVE.validate_python(rows[0]["ppc_rotated" if data.rotated else "ppc"])
        if not ppc > 0:
            raise ValueError("Scaler PPC must be positive")
        src_pixels, dst_pixels = data.src[0] * data.src[1], data.dst[0] * data.dst[1]
        read = src_pixels * data.src_bpp / 8 * data.fps * data.compression_ratio
        write = 0 if data.votf else dst_pixels * data.dst_bpp / 8 * data.fps
        required = max(src_pixels, dst_pixels) * data.fps / ppc / 1000
        choices = [r for r in perf.get("qos_table", []) if r["freq_mscl_khz"] >= required]
        selected = min(choices, key=lambda r: r["freq_mscl_khz"]) if choices else None
        out.update(
            read_bytes_s=read,
            write_bytes_s=write,
            source_KiB_s=(read + write) / 1024,
            ppc=ppc,
            required_clock_khz=required,
            selected_qos=selected,
            clock_status="supported" if selected else "infeasible",
        )
        if selected is None:
            out["status"] = "infeasible"
        out["notes"].append(
            "PPC format row is explicit; payload bpp alone cannot identify padded/packed formats. MIF reference scaling is not applied without a validated reference-unit contract."
        )
    else:
        bw = caps.get("bw_model") or {}
        params = bw.get("params") or {}
        floor = POSITIVE.validate_python(params["disp_refresh_rate_floor_hz"])
        ppc = POSITIVE.validate_python(params["ppc"])
        if floor <= 0 or ppc <= 0:
            raise ValueError("DPU floor and PPC must be positive")
        margin = 1100 + (12000 * data.dsc_slice_count + 20000) / data.panel_width
        clock = data.panel_width * data.panel_height * max(data.refresh_hz, floor) * margin / 1e6
        vote = sum(
            max(1, layer.src[0] / layer.dst[0])
            * max(1, layer.src[1] / layer.dst[1])
            * layer.bpp
            / 8
            * clock
            * (layer.dst[0] / data.panel_width if data.refresh_hz <= floor else 1)
            for layer in data.layers
        )
        traffic = sum(
            layer.src[0] * layer.src[1] * layer.bpp / 8 * data.refresh_hz for layer in data.layers
        )
        required = clock / ppc
        levels = [v for v in bw.get("disp_dfs_lv_khz", []) if v >= required]
        out.update(
            read_bytes_s=traffic,
            write_bytes_s=0,
            bts_read_vote_kB_s=vote,
            resol_clock_khz=clock,
            required_clock_khz=required,
            selected_disp_clock_khz=min(levels) if levels else None,
            clock_status="supported" if levels else "infeasible",
        )
        if not levels:
            out["status"] = "infeasible"
        out["notes"].append(
            "Unrotated uncompressed layers only; excludes RCD/writeback/bus/customer overhead. BTS vote is separate from surface traffic and is not added to energy traffic."
        )
    out["traffic_unit"] = "bytes/s"
    return out


def inputs_from_config(model: str, config: dict[str, Any], caps: dict[str, Any]) -> dict[str, Any]:
    sim = config.get("sim") or {}
    allowed = MODELS[model].model_fields
    raw = {key: value for key, value in sim.items() if key in allowed}
    raw["model"] = model
    if model == "abox":
        raw["aud_freq_khz"] = (config.get("dvfs") or {}).get("aud_freq_khz")
    if model == "dpu":
        if sim.get("composer") not in (None, "DPU_DIRECT", "GPU_FALLBACK", "M2M_SCALER_FALLBACK"):
            raise ValueError("Unsupported DPU composer")
        layers = []
        for layer in sim.get("layers", []):
            if any(layer.get(k) for k in ("rotation", "rotated", "compression", "writeback")):
                raise ValueError("DPU rotation/compression/writeback requires another model")
            layers.append({k: layer[k] for k in ("src", "dst", "bpp")})
        raw["layers"] = layers
        dsc = (caps.get("bw_model") or {}).get("params", {}).get("dsc_slice_count", {})
        raw["dsc_slice_count"] = sim.get("dsc_slice_count", dsc.get("value"))
    return raw


def evaluate_graph(graph, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    overrides = overrides or {}
    rows = []
    eligible = set()
    for node in graph.pipeline_nodes:
        node_id = str(node["id"])
        ip = graph.ip_catalog.get(str(node.get("ip_ref")))
        if ip is None or ip.id not in SUPPORTED_IPS:
            continue
        caps = ip.capabilities or {}
        model = GROUPS.get((caps.get("properties") or {}).get("ip_group"))
        cfg = (graph.variant.node_configs or {}).get(node_id) or {}
        if model is None or not cfg.get("sim") or (cfg["sim"].get("active") is False):
            continue
        eligible.add(node_id)
        raw: dict[str, Any] = {}
        try:
            raw = inputs_from_config(model, cfg, caps)
            if node_id in overrides:
                override = overrides[node_id]
                raw = override.model_dump() if hasattr(override, "model_dump") else override
                if raw.get("model") != model:
                    raise ValueError("Override model differs from node IP")
            result = evaluate(raw, caps)
        except ValidationError as exc:
            missing = all(e.get("input") is None or e["type"] == "missing" for e in exc.errors())
            result = {
                "model": model,
                "status": "missing_input" if missing else "invalid_input",
                "inputs": raw,
                "reason": str(exc),
                "power_mw": None,
            }
        except (ValueError, KeyError, TypeError) as exc:
            result = {"model": model, "status": "unsupported", "reason": str(exc), "power_mw": None}
        rows.append(
            {
                "node_id": node_id,
                "ip_ref": ip.id,
                "catalog_sha256": ip.yaml_sha256,
                "input_basis": "exploration" if node_id in overrides else "fixture",
                "declared_bw_kb_s": cfg.get("bw_kb_s"),
                "input_provenance": {"sim": cfg.get("sim"), "dvfs": cfg.get("dvfs")},
                **result,
            }
        )
    unknown = set(overrides) - eligible
    if unknown:
        raise ValueError(f"Driver override requires an active supported node: {sorted(unknown)}")
    return {
        "version": VERSION,
        "scenario_id": graph.scenario_id,
        "variant_id": graph.variant_id,
        "design_conditions": graph.variant.design_conditions or {},
        "rows": rows,
        "aggregation": "Per-endpoint estimates; not added to legacy DMA/power totals. Overlapping ownership must be resolved before aggregation.",
    }
