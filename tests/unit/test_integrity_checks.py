from __future__ import annotations

from scenario_db.integrity_checks import (
    IpModeCatalog,
    VariantOverlayTarget,
    validate_variant_overlay_targets,
)


def _target(**overrides):
    payload = {
        "scenario_id": "uc-camera-u",
        "variant_id": "v1",
        "base_pipeline": {
            "nodes": [{"id": "isp", "ip_ref": "ip-isp-v1"}],
            "edges": [],
            "buffers": {"REC": {"format": "YUV420"}},
        },
        "node_configs": {},
        "buffer_overrides": {},
        "topology_patch": {},
        "path_prefix": "payload.variant",
    }
    payload.update(overrides)
    return VariantOverlayTarget(**payload)


def test_variant_overlay_target_reports_missing_node_config_target():
    issues = validate_variant_overlay_targets(
        [_target(node_configs={"missing": {}})],
        IpModeCatalog({"ip-isp-v1": {"normal"}}),
    )

    assert [issue.code for issue in issues] == ["unknown_node_config"]
    assert issues[0].path == "payload.variant.node_configs.missing"


def test_variant_overlay_target_reports_non_object_node_config():
    issues = validate_variant_overlay_targets(
        [_target(node_configs={"isp": "not-an-object"})],
        IpModeCatalog({"ip-isp-v1": {"normal"}}),
    )

    assert [issue.code for issue in issues] == ["node_config_invalid"]
    assert issues[0].path == "payload.variant.node_configs.isp"


def test_variant_overlay_target_reports_unsupported_selected_mode():
    issues = validate_variant_overlay_targets(
        [_target(node_configs={"isp": {"selected_mode": "turbo"}})],
        IpModeCatalog({"ip-isp-v1": {"normal"}}),
    )

    assert [issue.code for issue in issues] == ["unsupported_selected_mode"]
    assert "turbo" in issues[0].message
    assert issues[0].path == "payload.variant.node_configs.isp.selected_mode"


def test_variant_overlay_target_reports_selected_mode_without_ip():
    issues = validate_variant_overlay_targets(
        [
            _target(
                base_pipeline={"nodes": [{"id": "sw_task"}], "buffers": {}},
                node_configs={"sw_task": {"selected_mode": "normal"}},
            )
        ],
        IpModeCatalog({}),
    )

    assert [issue.code for issue in issues] == ["selected_mode_without_ip"]


def test_variant_overlay_target_lenient_allows_selected_mode_when_modes_undeclared():
    """Default (bulk) policy: an IP with no declared modes cannot be validated,
    so selected_mode is accepted (ETL / import-bundle behavior)."""
    issues = validate_variant_overlay_targets(
        [_target(node_configs={"isp": {"selected_mode": "turbo"}})],
        IpModeCatalog({}),
    )

    assert issues == []


def test_variant_overlay_target_strict_rejects_selected_mode_when_modes_undeclared():
    """Strict (interactive Write) policy: an IP with no declared modes rejects
    any selected_mode. This preserves the historic Write API behavior."""
    issues = validate_variant_overlay_targets(
        [_target(node_configs={"isp": {"selected_mode": "turbo"}})],
        IpModeCatalog({}),
        strict_undeclared_modes=True,
    )

    assert [issue.code for issue in issues] == ["unsupported_selected_mode"]


def test_variant_overlay_target_skips_selected_mode_when_disabled():
    """Pipeline-patch impact uses existence-only mode: selected_mode must not
    introduce new blocking errors."""
    issues = validate_variant_overlay_targets(
        [_target(node_configs={"isp": {"selected_mode": "turbo"}})],
        IpModeCatalog({}),
        check_selected_mode=False,
        strict_undeclared_modes=True,
    )

    assert issues == []


def test_variant_overlay_target_allows_selected_mode_on_injected_node_when_disabled():
    issues = validate_variant_overlay_targets(
        [
            _target(
                topology_patch={"add_nodes": [{"id": "sw_eis"}]},
                node_configs={"sw_eis": {"kind": "sw_task"}},
            )
        ],
        IpModeCatalog({}),
        check_selected_mode=False,
    )

    assert issues == []


def test_variant_overlay_target_reports_missing_buffer_override_target():
    issues = validate_variant_overlay_targets(
        [_target(buffer_overrides={"MISSING": {"format": "P010"}})],
        IpModeCatalog({"ip-isp-v1": {"normal"}}),
    )

    assert [issue.code for issue in issues] == ["unknown_buffer_override"]
    assert issues[0].path == "payload.variant.buffer_overrides.MISSING"


def test_variant_overlay_target_without_path_prefix_emits_bare_paths():
    issues = validate_variant_overlay_targets(
        [_target(path_prefix="", buffer_overrides={"MISSING": {}})],
        IpModeCatalog({}),
    )

    assert issues[0].path == "buffer_overrides.MISSING"
