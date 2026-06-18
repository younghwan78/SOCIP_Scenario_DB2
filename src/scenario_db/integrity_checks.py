from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.definition import Scenario, ScenarioVariant


@dataclass(slots=True)
class IntegrityIssue:
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    document_kind: str
    document_id: str
    path: str
    fix_hint: str


@dataclass(slots=True)
class VariantOverlayTarget:
    """Surface-neutral description of one variant overlay to validate.

    ETL/import-health build these from ORM rows; the Write API builds them from
    staged payload dicts / import-bundle documents / pipeline-patch candidates.
    Keeping a single shape lets one engine serve every surface.
    """

    scenario_id: str
    variant_id: str
    base_pipeline: dict[str, Any]
    node_configs: dict[str, Any]
    buffer_overrides: dict[str, Any]
    topology_patch: dict[str, Any] = field(default_factory=dict)
    path_prefix: str = ""
    document_kind: str = "scenario.usecase"
    document_id: str | None = None


@dataclass(slots=True)
class IpModeCatalog:
    """Declared operating-mode ids per IP ref.

    An ip_ref absent from the map resolves to an empty set, i.e. "no declared
    modes". Callers decide whether an empty set means 'cannot validate, skip'
    (lenient, ETL/import-health/import-bundle) or 'reject any selected_mode'
    (strict, interactive Write staging) via ``strict_undeclared_modes``.
    """

    modes_by_ip_ref: dict[str, set[str]] = field(default_factory=dict)

    def modes_for(self, ip_ref: str | None) -> set[str]:
        if not ip_ref:
            return set()
        return self.modes_by_ip_ref.get(str(ip_ref), set())


def validate_scenario_identity_conventions(
    scenarios: list[Scenario],
) -> list[IntegrityIssue]:
    """Check Option A naming/matching conventions without changing DB keys."""

    issues: list[IntegrityIssue] = []
    scenarios_by_name: dict[str, list[Scenario]] = defaultdict(list)
    for scenario in scenarios:
        metadata = scenario.metadata_ or {}
        canonical = _as_text(metadata.get("canonical_usecase"))
        if canonical and str(scenario.id) in {canonical, f"uc-{canonical}"}:
            issues.append(
                IntegrityIssue(
                    severity="warning",
                    code="scenario_id_not_project_qualified",
                    message=(
                        f"Scenario {scenario.id} declares canonical_usecase '{canonical}' "
                        "but the scenario id is not project-qualified."
                    ),
                    document_kind="scenario.usecase",
                    document_id=str(scenario.id),
                    path="id",
                    fix_hint=(
                        "Keep canonical_usecase as the cross-project key and rename the "
                        "scenario id to a project-qualified DB identity."
                    ),
                )
            )
        name = _as_text(metadata.get("name"))
        if name:
            scenarios_by_name[name.casefold()].append(scenario)

    for rows in scenarios_by_name.values():
        project_refs = {str(row.project_ref) for row in rows}
        if len(rows) < 2 or len(project_refs) < 2:
            continue
        for scenario in rows:
            metadata = scenario.metadata_ or {}
            if metadata.get("canonical_usecase"):
                continue
            issues.append(
                IntegrityIssue(
                    severity="warning",
                    code="scenario_canonical_usecase_missing",
                    message=(
                        f"Scenario {scenario.id} has the same name as scenarios in other "
                        "projects but does not declare metadata.canonical_usecase."
                    ),
                    document_kind="scenario.usecase",
                    document_id=str(scenario.id),
                    path="metadata.canonical_usecase",
                    fix_hint=(
                        "Add metadata.canonical_usecase when logically equivalent usecases "
                        "must be compared across projects."
                    ),
                )
            )
    return issues


def validate_variant_overlay_targets(
    targets: list[VariantOverlayTarget],
    ip_modes: IpModeCatalog,
    *,
    check_selected_mode: bool = True,
    strict_undeclared_modes: bool = False,
) -> list[IntegrityIssue]:
    """Surface-neutral variant overlay reference engine.

    Emits the canonical integrity codes (``unknown_node_config``,
    ``node_config_invalid``, ``selected_mode_without_ip``,
    ``unsupported_selected_mode``, ``unknown_buffer_override``). Each surface
    keeps its own thin adapter to remap codes/paths to its public taxonomy.

    ``check_selected_mode=False`` restricts the engine to pure existence checks
    (used by pipeline-patch impact, which must not introduce new blocking modes
    on previously-valid patches). ``strict_undeclared_modes=True`` rejects a
    ``selected_mode`` whose IP declares no modes (interactive Write staging),
    while the default leniency skips it (bulk ETL/import paths).
    """

    issues: list[IntegrityIssue] = []
    for target in targets:
        base_pipeline = target.base_pipeline or {}
        base_nodes = {
            str(node.get("id")): node
            for node in (base_pipeline.get("nodes") or [])
            if isinstance(node, dict) and node.get("id")
        }
        buffer_ids = set((base_pipeline.get("buffers") or {}).keys())
        topology_patch = target.topology_patch or {}
        injected_nodes = {
            str(node.get("id"))
            for node in (topology_patch.get("add_nodes") or [])
            if isinstance(node, dict) and node.get("id")
        }
        known_nodes = set(base_nodes) | injected_nodes
        variant_ref = f"{target.scenario_id}/{target.variant_id}"
        document_id = target.document_id or target.scenario_id
        prefix = f"{target.path_prefix}." if target.path_prefix else ""

        for node_id, config in (target.node_configs or {}).items():
            node_id_text = str(node_id)
            path = f"{prefix}node_configs.{node_id_text}"
            if node_id_text not in known_nodes:
                issues.append(
                    IntegrityIssue(
                        severity="error",
                        code="unknown_node_config",
                        message=f"Variant {variant_ref} node_configs references missing node {node_id_text}",
                        document_kind=target.document_kind,
                        document_id=document_id,
                        path=path,
                        fix_hint="Fix node_configs key or add the node in pipeline.nodes/topology_patch.add_nodes.",
                    )
                )
                continue
            if not isinstance(config, dict):
                issues.append(
                    IntegrityIssue(
                        severity="error",
                        code="node_config_invalid",
                        message=f"Variant {variant_ref} node_config {node_id_text} must be an object",
                        document_kind=target.document_kind,
                        document_id=document_id,
                        path=path,
                        fix_hint="Use a mapping object for each node_configs entry.",
                    )
                )
                continue
            if not check_selected_mode:
                continue
            selected_mode = config.get("selected_mode")
            if selected_mode is None:
                continue
            node = base_nodes.get(node_id_text)
            ip_ref = node.get("ip_ref") if isinstance(node, dict) else None
            selected_mode_path = f"{path}.selected_mode"
            if not ip_ref:
                issues.append(
                    IntegrityIssue(
                        severity="error",
                        code="selected_mode_without_ip",
                        message=f"Variant {variant_ref} selected_mode requires an IP-backed node {node_id_text}",
                        document_kind=target.document_kind,
                        document_id=document_id,
                        path=selected_mode_path,
                        fix_hint="Move selected_mode to a base pipeline node that has ip_ref.",
                    )
                )
                continue
            modes = ip_modes.modes_for(ip_ref)
            if (strict_undeclared_modes or modes) and str(selected_mode) not in modes:
                issues.append(
                    IntegrityIssue(
                        severity="error",
                        code="unsupported_selected_mode",
                        message=(
                            f"Variant {variant_ref} selected_mode '{selected_mode}' "
                            f"is not supported by {ip_ref}"
                        ),
                        document_kind=target.document_kind,
                        document_id=document_id,
                        path=selected_mode_path,
                        fix_hint="Add the mode to ip.capabilities.operating_modes or fix selected_mode.",
                    )
                )

        for buffer_id in (target.buffer_overrides or {}):
            buffer_id_text = str(buffer_id)
            if buffer_id_text not in buffer_ids:
                issues.append(
                    IntegrityIssue(
                        severity="error",
                        code="unknown_buffer_override",
                        message=(
                            f"Variant {variant_ref} buffer_overrides references missing buffer "
                            f"{buffer_id_text}"
                        ),
                        document_kind=target.document_kind,
                        document_id=document_id,
                        path=f"{prefix}buffer_overrides.{buffer_id_text}",
                        fix_hint="Fix buffer_overrides key or add the buffer to pipeline.buffers.",
                    )
                )
    return issues


def variant_overlay_targets_from_rows(
    scenarios: list[Scenario],
    variants: list[ScenarioVariant],
) -> list[VariantOverlayTarget]:
    """Adapt ORM rows to the neutral target shape (ETL / import-health)."""

    scenario_by_id = {str(scenario.id): scenario for scenario in scenarios}
    targets: list[VariantOverlayTarget] = []
    for variant in variants:
        scenario_id = str(variant.scenario_id)
        scenario = scenario_by_id.get(scenario_id)
        if scenario is None:
            continue
        targets.append(
            VariantOverlayTarget(
                scenario_id=scenario_id,
                variant_id=str(variant.id),
                base_pipeline=scenario.pipeline or {},
                node_configs=variant.node_configs or {},
                buffer_overrides=variant.buffer_overrides or {},
                topology_patch=variant.topology_patch or {},
                path_prefix=f"variants.{variant.id}",
                document_id=scenario_id,
            )
        )
    return targets


def ip_mode_catalog_from_rows(ips: list[IpCatalog]) -> IpModeCatalog:
    """Build the operating-mode catalog from IP catalog ORM rows."""

    return IpModeCatalog({str(ip.id): _operating_mode_ids(ip) for ip in ips})


def validate_variant_overlay_integrity(
    scenarios: list[Scenario],
    variants: list[ScenarioVariant],
    ips: list[IpCatalog],
) -> list[IntegrityIssue]:
    """Validate variant overlay references shared by ETL and import-health.

    Backward-compatible wrapper over :func:`validate_variant_overlay_targets`.
    Keeps the historic lenient selected_mode behavior (undeclared IP modes are
    skipped) so loaded-DB and import-health output is byte-identical.
    """

    return validate_variant_overlay_targets(
        variant_overlay_targets_from_rows(scenarios, variants),
        ip_mode_catalog_from_rows(ips),
    )


def _operating_mode_ids(ip: IpCatalog | None) -> set[str]:
    if ip is None:
        return set()
    caps = ip.capabilities or {}
    return operating_mode_ids_from_capabilities(caps if isinstance(caps, dict) else {})


def operating_mode_ids_from_capabilities(capabilities: dict[str, Any]) -> set[str]:
    """Extract operating-mode ids from a capabilities mapping (dict or row).

    Accepts both the ``{id: {...}}`` map form and the ``[{"id": ...}]`` list
    form so it works for in-bundle IP documents and ORM rows alike.
    """

    modes = capabilities.get("operating_modes") if isinstance(capabilities, dict) else None
    if isinstance(modes, dict):
        return {str(key) for key in modes}
    result: set[str] = set()
    for mode in modes or []:
        if isinstance(mode, dict) and mode.get("id") is not None:
            result.add(str(mode["id"]))
        elif getattr(mode, "id", None) is not None:
            result.add(str(mode.id))
    return result


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
