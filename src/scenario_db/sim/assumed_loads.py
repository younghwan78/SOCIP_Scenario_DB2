"""Assumed IP loads declared on a variant (opt-in), e.g. GPU / NPU power before they are modelled as pipeline nodes.

At the spec stage some IPs that cost real power in a scenario (GPU for UHD120 / Pro / Portrait, NPU for segmentation)
are not pipeline nodes yet. A variant declares them in ``design_conditions``::

    design_conditions:
      assumed_gpu_mw: 350
      assumed_gpu_basis: "previous project UHD120 GPU rail mean"   # optional, shown in the report
      assumed_npu_mw: 120

Each ``assumed_<ip>_mw`` adds a constant to the IP (HW core) power and to the total of every case, so the case
ranking is unchanged and DVFS / compression deltas are unaffected. A variant without such keys computes exactly as
before (no engine revision change); declaring one changes the variant document and therefore its input hash.
"""

from __future__ import annotations

import math
import re
from typing import Any

_KEY = re.compile(r"^assumed_([a-z0-9][a-z0-9_]*?)_mw$")


def assumed_loads(conditions: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """``{ip: {"mw": float, "basis": str | None}}`` from ``design_conditions``; non-numeric or negative values are ignored."""
    out: dict[str, dict[str, Any]] = {}
    for key, value in (conditions or {}).items():
        m = _KEY.match(str(key))
        if not m or isinstance(value, bool):
            continue
        try:
            mw = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(mw) or mw <= 0:
            continue
        ip = m.group(1)
        basis = (conditions or {}).get(f"assumed_{ip}_basis")
        out[ip] = {"mw": round(mw, 3), "basis": str(basis) if basis not in (None, "") else None}
    return dict(sorted(out.items()))
