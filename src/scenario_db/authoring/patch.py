"""Deep-merge patches with explicit key removal.

Semantics
---------
* dict + dict  -> recursive merge
* anything else -> patch value replaces base value (lists are replaced whole)
* ``$unset: [k1, k2]`` inside a patch dict removes those keys from the base
* ``$append: {key: [items]}`` appends items to a base list (skipping items
  already present), e.g. one more ``topology_patch.remove_edges`` entry
"""

from __future__ import annotations

import copy
from typing import Any

UNSET = "$unset"
APPEND = "$append"


def deep_merge(base: Any, patch: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out = copy.deepcopy(base)
    for key in patch.get(UNSET, []) or []:
        out.pop(key, None)
    for key, items in (patch.get(APPEND) or {}).items():
        current = list(out.get(key) or [])
        current.extend(copy.deepcopy(i) for i in items if i not in current)
        out[key] = current
    for key, value in patch.items():
        if key in (UNSET, APPEND):
            continue
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def make_patch(base: Any, target: Any) -> Any:
    """Smallest patch such that ``deep_merge(base, patch) == target``.

    Returns ``None`` when base already equals target (dict case) so callers
    can drop empty patches.
    """
    if not isinstance(base, dict) or not isinstance(target, dict):
        return None if base == target else copy.deepcopy(target)
    patch: dict[str, Any] = {}
    removed = [k for k in base if k not in target]
    if removed:
        patch[UNSET] = removed
    for key, value in target.items():
        if key not in base:
            patch[key] = copy.deepcopy(value)
            continue
        if isinstance(base[key], dict) and isinstance(value, dict):
            sub = make_patch(base[key], value)
            if sub is not None:
                if sub == {} and value != base[key]:  # pragma: no cover - defensive
                    patch[key] = copy.deepcopy(value)
                elif sub:
                    patch[key] = sub
        elif base[key] != value or type(base[key]) is not type(value):
            patch[key] = copy.deepcopy(value)
    return patch or None


def diff_paths(a: Any, b: Any, prefix: str = "") -> list[str]:
    """Human-readable list of paths where two documents differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for key in sorted(set(a) | set(b), key=str):
            p = f"{prefix}.{key}" if prefix else str(key)
            if key not in a:
                out.append(f"+ {p}")
            elif key not in b:
                out.append(f"- {p}")
            else:
                out.extend(diff_paths(a[key], b[key], p))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(diff_paths(x, y, f"{prefix}[{i}]"))
        return out
    if a != b or type(a) is not type(b):
        return [f"~ {prefix}"]
    return []
