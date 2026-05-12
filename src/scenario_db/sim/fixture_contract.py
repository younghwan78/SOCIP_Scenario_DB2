from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

import yaml


IssueSeverity = Literal["error", "warning", "borrowable"]
ContractStatus = Literal["ready", "warning", "blocked"]

COMPUTE_CATEGORIES = {"camera", "codec", "compute", "cpu", "display", "gpu", "npu"}
EXTERNAL_CATEGORIES = {"sensor", "panel"}
SUPPORT_CATEGORIES = {"memory"}
SIM_PARAM_KEYS = {
    "ppc",
    "unit_power_mw_mp",
    "idc",
    "vdd",
    "dvfs_group",
    "max_clock_mhz",
}


@dataclass(frozen=True, slots=True)
class ContractIssue:
    severity: IssueSeverity
    code: str
    message: str
    path: str | None = None
    ip_ref: str | None = None
    category: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.path:
            result["path"] = self.path
        if self.ip_ref:
            result["ip_ref"] = self.ip_ref
        if self.category:
            result["category"] = self.category
        return result


def validate_soc_sim_contract(
    documents: Iterable[dict[str, Any]],
    *,
    soc_id: str | None = None,
) -> dict[str, Any]:
    """Validate whether a SoC fixture set has enough metadata for simulation.

    This is a catalog/fixture-level contract check. It deliberately differs from
    scenario readiness: missing compute ppc on an active workload still blocks a
    scenario run, while a SoC-level unused IP without sim params can be marked as
    borrowable during early architecture exploration.
    """

    docs = [doc for doc in documents if isinstance(doc, dict)]
    soc_docs = {str(doc.get("id")): doc for doc in docs if doc.get("kind") == "soc" and doc.get("id")}
    ip_docs = {str(doc.get("id")): doc for doc in docs if doc.get("kind") == "ip" and doc.get("id")}
    issues: list[ContractIssue] = []

    if soc_id:
        soc = soc_docs.get(soc_id)
        if soc is None:
            issues.append(
                ContractIssue(
                    "error",
                    "SOC_NOT_FOUND",
                    f"SoC fixture not found: {soc_id}",
                    path="soc",
                )
            )
            return _report(soc_id, None, {}, issues)
    elif len(soc_docs) == 1:
        soc_id, soc = next(iter(soc_docs.items()))
    elif not soc_docs:
        issues.append(ContractIssue("error", "SOC_NOT_FOUND", "No SoC fixture was provided.", path="soc"))
        return _report("unknown", None, {}, issues)
    else:
        issues.append(
            ContractIssue(
                "error",
                "SOC_AMBIGUOUS",
                "Multiple SoC fixtures were provided; pass soc_id explicitly.",
                path="soc",
            )
        )
        return _report("ambiguous", None, {}, issues)

    assert soc is not None
    soc_ip_refs = [str(item.get("ref")) for item in soc.get("ips") or [] if isinstance(item, dict) and item.get("ref")]
    seen_refs: set[str] = set()
    compute_refs: list[str] = []
    external_refs: list[str] = []
    support_refs: list[str] = []

    for idx, ip_ref in enumerate(soc_ip_refs):
        if ip_ref in seen_refs:
            issues.append(
                ContractIssue(
                    "warning",
                    "DUPLICATE_SOC_IP_REF",
                    f"SoC references the same IP more than once: {ip_ref}",
                    path=f"soc.ips[{idx}].ref",
                    ip_ref=ip_ref,
                )
            )
            continue
        seen_refs.add(ip_ref)
        ip_doc = ip_docs.get(ip_ref)
        if ip_doc is None:
            issues.append(
                ContractIssue(
                    "error",
                    "IP_REF_NOT_FOUND",
                    f"SoC references an IP catalog that is not present: {ip_ref}",
                    path=f"soc.ips[{idx}].ref",
                    ip_ref=ip_ref,
                )
            )
            continue

        category = _category(ip_doc)
        if category in EXTERNAL_CATEGORIES or _looks_like_sensor_or_panel(ip_doc):
            external_refs.append(ip_ref)
            issues.extend(_validate_external_ip(ip_doc, soc_id=soc_id))
        elif category in SUPPORT_CATEGORIES:
            support_refs.append(ip_ref)
        else:
            compute_refs.append(ip_ref)
            issues.extend(_validate_compute_ip(ip_doc, soc_id=soc_id))

    if not external_refs:
        issues.append(
            ContractIssue(
                "warning",
                "NO_EXTERNAL_DEVICE_CATALOG",
                "No sensor/display external device catalog is referenced by this SoC; source/sink timing may need project-level fallback.",
                path="soc.ips",
            )
        )

    summary = {
        "soc_ip_count": len(soc_ip_refs),
        "resolved_ip_count": len(seen_refs & set(ip_docs)),
        "compute_ip_count": len(compute_refs),
        "external_ip_count": len(external_refs),
        "support_ip_count": len(support_refs),
        "error_count": sum(1 for issue in issues if issue.severity == "error"),
        "warning_count": sum(1 for issue in issues if issue.severity == "warning"),
        "borrowable_count": sum(1 for issue in issues if issue.severity == "borrowable"),
    }
    return _report(soc_id or str(soc.get("id") or "unknown"), soc, summary, issues)


def load_fixture_documents(root: Path) -> list[dict[str, Any]]:
    """Load mapped canonical YAML documents from a fixture directory."""

    documents: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("kind"):
            documents.append(raw)
    return documents


def _validate_compute_ip(ip_doc: dict[str, Any], *, soc_id: str) -> list[ContractIssue]:
    ip_ref = str(ip_doc.get("id"))
    category = _category(ip_doc)
    issues: list[ContractIssue] = []
    compatible_soc = ip_doc.get("compatible_soc") or []
    if compatible_soc and soc_id not in {str(item) for item in compatible_soc}:
        issues.append(
            ContractIssue(
                "warning",
                "COMPATIBLE_SOC_MISMATCH",
                f"{ip_ref} does not list {soc_id} in compatible_soc.",
                path=f"{ip_ref}.compatible_soc",
                ip_ref=ip_ref,
                category=category,
            )
        )

    sim = _sim_block(ip_doc)
    if not sim:
        issues.append(
            ContractIssue(
                "borrowable",
                "BORROWABLE_SIM_PARAMS",
                "No capabilities.sim block is defined; early exploration can borrow ppc/unit power/DVFS metadata from a mapping profile.",
                path=f"{ip_ref}.capabilities.sim",
                ip_ref=ip_ref,
                category=category,
            )
        )
        return issues

    param_blocks = _sim_param_blocks(sim)
    if not any(_positive(block.get("ppc")) for block in param_blocks):
        issues.append(
            ContractIssue(
                "error",
                "MISSING_PPC",
                "No positive ppc was found in capabilities.sim; active compute workloads cannot resolve clock/timing.",
                path=f"{ip_ref}.capabilities.sim",
                ip_ref=ip_ref,
                category=category,
            )
        )
    if not any(_positive(block.get("unit_power_mw_mp")) for block in param_blocks):
        issues.append(
            ContractIssue(
                "warning",
                "MISSING_UNIT_POWER",
                "No positive unit_power_mw_mp was found; core power will be zero unless a mapping profile supplies a borrowed value.",
                path=f"{ip_ref}.capabilities.sim",
                ip_ref=ip_ref,
                category=category,
            )
        )
    if not any(block.get("dvfs_group") for block in param_blocks):
        issues.append(
            ContractIssue(
                "warning",
                "MISSING_DVFS_GROUP",
                "No dvfs_group was found; SoC profile defaults or explicit mapping are required.",
                path=f"{ip_ref}.capabilities.sim",
                ip_ref=ip_ref,
                category=category,
            )
        )
    if not any(block.get("vdd") for block in param_blocks):
        issues.append(
            ContractIssue(
                "warning",
                "MISSING_VDD",
                "No VDD domain was found; power-domain voltage alignment may be incomplete.",
                path=f"{ip_ref}.capabilities.sim",
                ip_ref=ip_ref,
                category=category,
            )
        )
    return issues


def _validate_external_ip(ip_doc: dict[str, Any], *, soc_id: str) -> list[ContractIssue]:
    ip_ref = str(ip_doc.get("id"))
    category = _category(ip_doc)
    issues: list[ContractIssue] = []
    compatible_soc = ip_doc.get("compatible_soc") or []
    if compatible_soc and soc_id not in {str(item) for item in compatible_soc}:
        issues.append(
            ContractIssue(
                "warning",
                "COMPATIBLE_SOC_MISMATCH",
                f"{ip_ref} does not list {soc_id} in compatible_soc.",
                path=f"{ip_ref}.compatible_soc",
                ip_ref=ip_ref,
                category=category,
            )
        )

    properties = ((ip_doc.get("capabilities") or {}).get("properties") or {})
    if category == "sensor" or "sensor" in ip_ref.lower():
        modes = properties.get("modes") or {}
        if not modes:
            issues.append(
                ContractIssue(
                    "warning",
                    "SENSOR_MODES_MISSING",
                    "Sensor catalog has no modes; source size/fps/v-valid timing must come from project fallback.",
                    path=f"{ip_ref}.capabilities.properties.modes",
                    ip_ref=ip_ref,
                    category=category,
                )
            )
            return issues
        required = {"sensor_size", "sensor_fps", "sensor_format", "sensor_bitwidth", "sensor_mipi_speed"}
        for mode_name, mode in modes.items():
            if not isinstance(mode, dict):
                continue
            missing = sorted(key for key in required if mode.get(key) in (None, "", []))
            if missing:
                issues.append(
                    ContractIssue(
                        "warning",
                        "SENSOR_MODE_METADATA_INCOMPLETE",
                        f"Sensor mode {mode_name} is missing: {', '.join(missing)}.",
                        path=f"{ip_ref}.capabilities.properties.modes.{mode_name}",
                        ip_ref=ip_ref,
                        category=category,
                    )
                )
            has_vvalid_inputs = mode.get("sensor_pclk") and mode.get("sensor_line_length_pck")
            if not has_vvalid_inputs:
                issues.append(
                    ContractIssue(
                        "warning",
                        "SENSOR_VVALID_INPUTS_MISSING",
                        f"Sensor mode {mode_name} has no pclk/line_length_pck; v-valid timing cannot be calculated directly.",
                        path=f"{ip_ref}.capabilities.properties.modes.{mode_name}",
                        ip_ref=ip_ref,
                        category=category,
                    )
                )
    elif category in {"display", "panel"} or "panel" in ip_ref.lower():
        if not properties.get("display_size"):
            issues.append(
                ContractIssue(
                    "warning",
                    "DISPLAY_SIZE_MISSING",
                    "Display catalog has no display_size; sink size/layout must come from project fallback.",
                    path=f"{ip_ref}.capabilities.properties.display_size",
                    ip_ref=ip_ref,
                    category=category,
                )
            )
        if not properties.get("refresh_rates"):
            issues.append(
                ContractIssue(
                    "warning",
                    "DISPLAY_REFRESH_RATES_MISSING",
                    "Display catalog has no refresh_rates; sink timing must come from project fallback.",
                    path=f"{ip_ref}.capabilities.properties.refresh_rates",
                    ip_ref=ip_ref,
                    category=category,
                )
            )
    return issues


def _report(
    soc_id: str,
    soc: dict[str, Any] | None,
    summary: dict[str, Any],
    issues: list[ContractIssue],
) -> dict[str, Any]:
    status: ContractStatus
    if any(issue.severity == "error" for issue in issues):
        status = "blocked"
    elif issues:
        status = "warning"
    else:
        status = "ready"
    return {
        "status": status,
        "soc_id": soc_id,
        "process_node": soc.get("process_node") if soc else None,
        "memory_type": soc.get("memory_type") if soc else None,
        "summary": summary,
        "errors": [issue.as_dict() for issue in issues if issue.severity == "error"],
        "warnings": [issue.as_dict() for issue in issues if issue.severity == "warning"],
        "borrowable": [issue.as_dict() for issue in issues if issue.severity == "borrowable"],
    }


def _category(ip_doc: dict[str, Any]) -> str:
    return str(ip_doc.get("category") or "").lower()


def _looks_like_sensor_or_panel(ip_doc: dict[str, Any]) -> bool:
    text = f"{ip_doc.get('id', '')} {ip_doc.get('category', '')}".lower()
    return "sensor" in text or "panel" in text


def _sim_block(ip_doc: dict[str, Any]) -> dict[str, Any]:
    capabilities = ip_doc.get("capabilities") or {}
    sim = capabilities.get("sim") or (capabilities.get("properties") or {}).get("sim") or {}
    return sim if isinstance(sim, dict) else {}


def _sim_param_blocks(value: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if any(key in value for key in SIM_PARAM_KEYS):
            blocks.append(value)
        for item in value.values():
            blocks.extend(_sim_param_blocks(item))
    elif isinstance(value, list):
        for item in value:
            blocks.extend(_sim_param_blocks(item))
    return blocks


def _positive(value: Any) -> bool:
    try:
        return float(value or 0.0) > 0.0
    except (TypeError, ValueError):
        return False
