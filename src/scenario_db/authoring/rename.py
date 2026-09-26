"""ID rename rules used when a platform/project inherits from another.

Rules are ordered substring replacements applied to document ids
(``[{from: s5e9965, to: s5e9975}]``). The resulting old->new id map is then
applied to every string value that is exactly an id, or an id followed by a
``.`` / ``@`` path suffix (e.g. ``ip-dpu-s5e9965.capabilities.bw_model``).
"""

from __future__ import annotations

import re
from typing import Any, Iterable


def apply_rules(value: str, rules: Iterable[dict]) -> str:
    for rule in rules or []:
        value = value.replace(str(rule["from"]), str(rule["to"]))
    return value


def build_id_map(ids: Iterable[str], rules: Iterable[dict]) -> dict[str, str]:
    rules = list(rules or [])
    out = {}
    for i in ids:
        new = apply_rules(i, rules)
        if new != i:
            out[i] = new
    return out


def rename_value(value: Any, id_map: dict[str, str]) -> Any:
    if not id_map:
        return value
    pattern = re.compile(
        r"^(" + "|".join(re.escape(k) for k in sorted(id_map, key=len, reverse=True)) + r")(?=$|[.@])"
    )

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            return pattern.sub(lambda m: id_map[m.group(1)], v, count=1)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {walk(k) if isinstance(k, str) else k: walk(x) for k, x in v.items()}
        return v

    return walk(value)
