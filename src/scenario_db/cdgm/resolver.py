from __future__ import annotations

from copy import deepcopy
from typing import Any


def resolve_cdgm_arch_info(
    graph: Any,
    *,
    dvfs_domains: dict[str, Any],
    profile: Any | None = None,
) -> dict[str, Any]:
    """Project active scenario graph IP metadata into CDGM arch_info rows."""

    rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    rows_by_role: dict[str, dict[str, Any]] = {}

    for node in getattr(graph, "pipeline_nodes", []) or []:
        if not isinstance(node, dict):
            continue
        ip_ref = str(node.get("ip_ref") or "")
        if not ip_ref:
            continue
        ip_row = (getattr(graph, "ip_catalog", None) or {}).get(ip_ref)
        if ip_row is None:
            continue
        cdgm_roles = _cdgm_roles(ip_row)
        for role_key, role in cdgm_roles.items():
            if not isinstance(role, dict):
                continue
            row = _row_from_role(
                role_key=str(role_key),
                role=role,
                ip_ref=ip_ref,
                node_id=str(node.get("id") or ""),
                source=role.get("source") if isinstance(role.get("source"), dict) else {"kind": "cdgm_roles"},
            )
            rows.append(row)
            rows_by_role[row["role_key"]] = row

    for role_key, override in _matching_profile_overrides(profile, graph).items():
        base = rows_by_role.get(str(override.get("extends") or ""))
        merged = deepcopy(base) if base else {}
        merged.update(_row_from_role(
            role_key=str(role_key),
            role=override,
            ip_ref=str(override.get("ip_ref") or merged.get("ip_ref") or ""),
            node_id=str(override.get("node_id") or merged.get("node_id") or ""),
            source={"kind": "profile_override", "profile_ref": getattr(profile, "id", None)},
        ))
        rows.append(merged)
        rows_by_role[str(role_key)] = merged

    for index, row in enumerate(rows):
        domain = str(row.get("dvfs_domain") or "")
        if domain and domain not in dvfs_domains:
            issues.append(
                _issue(
                    "error",
                    "cdgm_dvfs_domain_not_found",
                    f"CDGM role {row.get('role_key')} references missing DVFS domain: {domain}",
                    f"arch_info_rows[{index}].dvfs_domain",
                )
            )
        if row.get("path_type") == "nrt" and not row.get("pos"):
            issues.append(
                _issue(
                    "error",
                    "cdgm_nrt_pos_missing",
                    f"NRT CDGM role {row.get('role_key')} must declare pos",
                    f"arch_info_rows[{index}].pos",
                )
            )

    return {
        "scenario_id": getattr(graph, "scenario_id", None),
        "variant_id": getattr(graph, "variant_id", None),
        "arch_info_rows": rows,
        "issues": issues,
    }


def _cdgm_roles(ip_row: Any) -> dict[str, Any]:
    capabilities = getattr(ip_row, "capabilities", None) or {}
    sim = capabilities.get("sim") if isinstance(capabilities, dict) else {}
    if not isinstance(sim, dict):
        return {}
    roles = sim.get("cdgm_roles") or {}
    return roles if isinstance(roles, dict) else {}


def _row_from_role(
    *,
    role_key: str,
    role: dict[str, Any],
    ip_ref: str,
    node_id: str,
    source: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ip_ref": ip_ref,
        "node_id": node_id,
        "role_key": role_key,
        "arch_ip": str(role.get("arch_ip") or role_key),
        "path_type": str(role.get("path_type") or "generic"),
        "pos": _pos_text(role.get("pos")),
        "ppc": float(role.get("ppc") or 0.0),
        "vdd": role.get("vdd"),
        "dvfs_domain": role.get("dvfs_domain"),
        "source": source,
    }


def _pos_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "+".join(str(item) for item in value if item)
    return ""


def _matching_profile_overrides(profile: Any | None, graph: Any) -> dict[str, dict[str, Any]]:
    if profile is None:
        return {}
    overrides = getattr(profile, "role_overrides", None)
    if overrides is None and isinstance(profile, dict):
        overrides = profile.get("role_overrides")
    if not isinstance(overrides, dict):
        return {}
    return {
        str(role_key): override
        for role_key, override in overrides.items()
        if isinstance(override, dict) and _conditions_match(override.get("when") or {}, graph)
    }


def _conditions_match(conditions: dict[str, Any], graph: Any) -> bool:
    if not conditions:
        return True
    context = _condition_context(graph)
    for key, expected in conditions.items():
        actual = context.get(str(key))
        if isinstance(actual, list):
            if expected not in actual:
                return False
        elif actual != expected:
            return False
    return True


def _condition_context(graph: Any) -> dict[str, Any]:
    variant = getattr(graph, "variant", None)
    design = getattr(variant, "design_conditions", None) or {}
    scenario = getattr(graph, "scenario", None)
    metadata = getattr(scenario, "metadata_", None) or {}
    context = dict(design) if isinstance(design, dict) else {}
    context["scenario_domain"] = _metadata_values(metadata.get("domain"))
    context["scenario_category"] = _metadata_values(metadata.get("category"))
    context["variant_id"] = getattr(graph, "variant_id", None)
    context["variant_tag"] = getattr(variant, "tags", None) or []
    return context


def _metadata_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _issue(severity: str, code: str, message: str, path: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message, "path": path}
