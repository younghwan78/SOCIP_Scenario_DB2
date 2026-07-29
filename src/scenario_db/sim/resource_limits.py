from __future__ import annotations

from collections.abc import Iterable
from typing import Any

DEFAULT_MAX_SWEEP_CASES = 500


def enforce_sweep_case_limit(
    axes: Iterable[Any],
    max_cases: int = DEFAULT_MAX_SWEEP_CASES,
) -> int:
    """Reject a Cartesian sweep before it allocates expanded case payloads."""

    case_count = 1
    for axis in axes:
        values = axis.get("values") if isinstance(axis, dict) else getattr(axis, "values", None)
        if not isinstance(values, list) or not values:
            # The compiler's normal validation owns the detailed shape error.
            continue
        if case_count > max_cases // len(values):
            raise ValueError(f"sweep expands beyond configured maximum {max_cases} cases")
        case_count *= len(values)
    return case_count
