"""Deep-merge patches with explicit key removal.

Semantics
---------
* dict + dict  -> recursive merge
* anything else -> patch value replaces base value (lists are replaced whole)
* ``$unset: [k1, k2]`` inside a patch dict removes those keys from the base
* ``$append: {key: [items]}`` appends items to a base list (skipping items
  already present), e.g. one more ``topology_patch.remove_edges`` entry
* ``$remove: {key: [items]}`` removes items from a base list. A dict item is a
  selector: it removes every base dict whose given keys are equal, e.g.
  ``$remove: {add_edges: [{from: mcsc, to: mfc_enc}]}``
* ``$items: {key: {by: name, patch: {ID: {...}}, remove: [ID], add: [{...}]}}``
  edits a list of dicts by an id field (``by``, default ``id``) instead of
  replacing it whole, e.g. one DMA port of ``capabilities.properties.modules``.
  ``patch`` deep-merges (unknown id -> error), ``remove`` drops, ``add`` appends
  (existing id -> error).

Order inside one patch dict: ``$unset`` -> ``$remove`` -> ``$append`` -> ``$items`` -> keys.
"""

from __future__ import annotations

import copy
from typing import Any

from scenario_db.authoring.errors import AuthoringError

UNSET = "$unset"
APPEND = "$append"
REMOVE = "$remove"
ITEMS = "$items"
OPS = (UNSET, APPEND, REMOVE, ITEMS)


class PatchError(AuthoringError):
    pass


def _selects(item: Any, sel: Any) -> bool:
    if isinstance(sel, dict) and isinstance(item, dict):
        return all(item.get(k) == v for k, v in sel.items())
    return item == sel


def _edit_items(current: list, spec: dict, key: str) -> list:
    by = spec.get("by", "id")
    out = [copy.deepcopy(i) for i in current]
    if any(not isinstance(i, dict) or by not in i for i in out):
        raise PatchError(f"$items.{key}: each item needs '{by}'")
    ids = [i.get(by) if isinstance(i, dict) else None for i in out]
    if any(ids.count(i) > 1 for i in ids):
        raise PatchError(f"$items.{key}: duplicate '{by}' in current list")
    for rid in spec.get("remove") or []:
        if rid not in ids:
            raise PatchError(f"$items.{key}: remove unknown {by}='{rid}'")
    out = [i for i, x in zip(out, ids) if x not in set(spec.get("remove") or [])]
    ids = [i.get(by) if isinstance(i, dict) else None for i in out]
    for pid, sub in (spec.get("patch") or {}).items():
        if pid not in ids:
            raise PatchError(f"$items.{key}: patch unknown {by}='{pid}'")
        idx = ids.index(pid)
        out[idx] = deep_merge(out[idx], sub)
        if not isinstance(out[idx], dict) or out[idx].get(by) != pid:
            raise PatchError(f"$items.{key}: patch cannot change '{by}'; use remove/add")
    for item in spec.get("add") or []:
        if not isinstance(item, dict) or by not in item:
            raise PatchError(f"$items.{key}: add item needs '{by}'")
        if item[by] in ids:
            raise PatchError(f"$items.{key}: add duplicate {by}='{item[by]}' (use patch)")
        out.append(copy.deepcopy(item))
        ids.append(item[by])
    return out


def deep_merge(base: Any, patch: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out = copy.deepcopy(base)
    for key in patch.get(UNSET, []) or []:
        out.pop(key, None)
    for key, sels in (patch.get(REMOVE) or {}).items():
        if key in out:
            out[key] = [i for i in (out[key] or []) if not any(_selects(i, s) for s in sels)]
    for key, items in (patch.get(APPEND) or {}).items():
        current = list(out.get(key) or [])
        current.extend(copy.deepcopy(i) for i in items if i not in current)
        out[key] = current
    for key, spec in (patch.get(ITEMS) or {}).items():
        out[key] = _edit_items(list(out.get(key) or []), spec or {}, key)
    for key, value in patch.items():
        if key in OPS:
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
