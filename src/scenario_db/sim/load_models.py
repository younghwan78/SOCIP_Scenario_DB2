"""Workload load models: what sets an IP's processing rate beyond size x fps (review finding D-03).

The compute model times an IP as ``pixels / (ppc x clock)`` with one ``ppc`` per IP mode. A decoder's
rate also depends on the codec and the bitrate. A load model turns those conditions into the effective
``ppc`` of one workload, so the clock rule, timing and power stay the same calculation.

Registered models (``LOAD_MODELS``, like ``POWER_MODELS``):

``codec-throughput-v1``
    Per codec (and direction) pixel throughput plus an entropy term per bit::

        cycles / frame = pixels / ppc_codec + bitrate x 1e6 / fps x cycles_per_bit
        ppc_effective  = pixels / (cycles / frame)

    Coefficients come from the IP catalog, ``capabilities.sim.load_models.codec-throughput-v1``::

        codecs:                      # explicit, per <CODEC>_<DEC|ENC> of properties.codecs
          AV1_DEC: {ppc: 1.0, cycles_per_bit: 0.4}
        derive: codec_limits         # or: ppc_codec from the codec's declared limit
        clock_mhz: 663               # ... reached at this clock (max_resolution x max_fps)

Opt-in per node: ``node_configs.<node>.sim.load_model: codec-throughput-v1`` (``none`` opts out), or per
role in the catalog: ``load_models.codec-throughput-v1.roles: [decoder]``. The codec is
``sim.codec`` or the variant ``design_conditions.codec``; the bitrate ``sim.bitrate_mbps`` or
``design_conditions.bitrate_mbps`` (no bitrate = no entropy term). A node that opts in without the
coefficients it needs is refused (no silent fallback to the mode ppc).
"""

from __future__ import annotations

from typing import Any, Protocol

RESOLUTION_PX: dict[str, tuple[int, int]] = {
    "HD": (1280, 720), "FHD": (1920, 1080), "QHD": (2560, 1440), "UHD": (3840, 2160), "4K": (3840, 2160),
    "8K": (7680, 4320),
}
CODEC_ALIASES = {"H264": "H264", "AVC": "H264", "H.264": "H264", "HEVC": "HEVC", "H265": "HEVC", "H.265": "HEVC",
                 "VP9": "VP9", "AV1": "AV1", "APV": "APV", "BPG": "BPG"}


class LoadModel(Protocol):
    id: str

    def effective(self, *, caps: dict[str, Any], node_id: str, role: str, sim: dict[str, Any],
                  design: dict[str, Any], width: int, height: int, fps: float, base_ppc: float,
                  params: dict[str, Any] | None = None) -> dict[str, Any]:
        """The effective ``ppc`` of the workload and the trace of how it was reached."""
        ...


def _codec(value: Any, node_id: str) -> tuple[str, str | None]:
    """(codec, direction from a ``_DEC`` / ``_ENC`` suffix or None) of ``H264``, ``h.264``, ``AV1_DEC`` …"""
    text = str(value or "").strip().upper().replace("-", "")
    direction = None
    for suffix, d in (("_DEC", "decode"), ("_ENC", "encode")):
        if text.endswith(suffix):
            text, direction = text[: -len(suffix)], d
    code = CODEC_ALIASES.get(text) or CODEC_ALIASES.get(text.replace(".", ""))
    if code is None:
        raise ValueError(f"{node_id}: load model needs a known codec (sim.codec, the node's codec or "
                         f"design_conditions.codec / codec_mfc), got {value!r}")
    return code, direction


def _direction(sim: dict[str, Any], role: str, from_codec: str | None) -> str:
    if sim.get("direction") in ("decode", "encode"):
        return str(sim["direction"])
    if from_codec:
        return from_codec
    return "encode" if "enc" in role.lower() else "decode"


class CodecThroughputV1:
    id = "codec-throughput-v1"

    def effective(self, *, caps, node_id, role, sim, design, width, height, fps, base_ppc, params=None):
        cfg = params if params is not None else ((caps.get("sim") or {}).get("load_models") or {}).get(self.id)
        if not isinstance(cfg, dict):
            raise ValueError(f"{node_id}: load model {self.id} needs coefficients (the pipeline node's load_model "
                             f"or capabilities.sim.load_models.{self.id} in the IP catalog)")
        if "codecs" in cfg and not isinstance(cfg["codecs"], dict):
            raise ValueError(f"{node_id}: load_model codecs must map <CODEC>_<DEC|ENC> to {{ppc, cycles_per_bit}}")
        codec, suffix = _codec(sim.get("codec") or design.get("codec") or design.get("codec_mfc"), node_id)
        direction = _direction(sim, role, suffix)
        key = f"{codec}_{'DEC' if direction == 'decode' else 'ENC'}"
        row = (cfg.get("codecs") or {}).get(key) or {}
        cycles_per_bit = float(row.get("cycles_per_bit") or cfg.get("cycles_per_bit") or 0.0)
        if row.get("ppc") is not None:
            ppc_codec, source = float(row["ppc"]), "catalog"
        elif cfg.get("derive") == "codec_limits":
            table = ((caps.get("properties") or {}).get("codecs") or {}).get("decoders" if direction == "decode" else "encoders") or {}
            limit = table.get(key)
            clock = float(cfg.get("clock_mhz") or 0.0)
            size = RESOLUTION_PX.get(str((limit or {}).get("max_resolution") or "").upper())
            if not limit or size is None or not limit.get("max_fps") or clock <= 0:
                raise ValueError(f"{node_id}: {key} has no declared limit (max_resolution, max_fps) or the model has no clock_mhz")
            ppc_codec = size[0] * size[1] * float(limit["max_fps"]) / (clock * 1e6)
            source = f"codec_limits ({limit['max_resolution']}{int(limit['max_fps'])} at {clock:g} MHz)"
        else:
            raise ValueError(f"{node_id}: load model {self.id} has no coefficient for {key} (codecs.{key}.ppc or derive: codec_limits)")
        if ppc_codec <= 0:
            raise ValueError(f"{node_id}: {key} ppc must be > 0")
        pixels = float(width * height)
        bitrate = sim.get("bitrate_mbps", design.get("bitrate_mbps"))
        bits_per_frame = float(bitrate) * 1e6 / fps if bitrate and fps > 0 else 0.0
        cycles = (pixels / ppc_codec if pixels > 0 else 0.0) + bits_per_frame * cycles_per_bit
        effective = pixels / cycles if pixels > 0 and cycles > 0 else ppc_codec
        return {
            "model": self.id, "codec": key, "direction": direction, "ppc_codec": round(ppc_codec, 4), "ppc_source": source,
            "bitrate_mbps": float(bitrate) if bitrate else None, "cycles_per_bit": cycles_per_bit,
            "entropy_cycles_per_frame": round(bits_per_frame * cycles_per_bit, 1),
            "ppc_effective": round(effective, 4), "ppc_mode": base_ppc,
        }


LOAD_MODELS: dict[str, LoadModel] = {CodecThroughputV1.id: CodecThroughputV1()}


def load_model_for(caps: dict[str, Any], sim: dict[str, Any], role: str,
                   node: dict[str, Any] | None = None) -> tuple[str | None, dict[str, Any] | None]:
    """(model id, coefficients declared on the pipeline node or None = the catalog's) of a node.

    In order: the variant's ``sim.load_model`` (``none`` = opt out); the scenario pipeline node's
    ``load_model: {ref, ...coefficients}`` (scenario-local assumptions: the shared IP catalog, and so
    every other scenario's input hash, stays as it is); a catalog model whose ``roles`` lists the node's role.
    """
    declared = (node or {}).get("load_model")
    node_params = declared if isinstance(declared, dict) else None
    own = sim.get("load_model")
    if own is not None:
        if str(own).lower() == "none":
            return None, None
        return str(own), node_params if node_params and node_params.get("ref") == str(own) else None
    if node_params and node_params.get("ref"):
        return str(node_params["ref"]), node_params
    for model_id, cfg in ((caps.get("sim") or {}).get("load_models") or {}).items():
        if isinstance(cfg, dict) and role in (cfg.get("roles") or []):
            return str(model_id), None
    return None, None


def resolve_load_model(model_id: str, node_id: str) -> LoadModel:
    model = LOAD_MODELS.get(model_id)
    if model is None:
        raise ValueError(f"{node_id}: unknown load model {model_id!r} (registered: {sorted(LOAD_MODELS)})")
    return model
