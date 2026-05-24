from __future__ import annotations

from scenario_db.query_engine.field_registry import field_definition, field_definitions, is_supported_field


def test_field_registry_allows_only_registered_or_safe_dynamic_fields() -> None:
    assert is_supported_field("topology.uses_ip")
    assert is_supported_field("axis.resolution")
    assert is_supported_field("axis.sensor.mode")
    assert is_supported_field("evidence.latest.kpi.total_power_mw")

    assert not is_supported_field("raw.sql")
    assert not is_supported_field("axis.$bad")
    assert not is_supported_field("evidence.latest.kpi.")


def test_field_registry_defines_dynamic_field_types_and_order() -> None:
    axis_definition = field_definition("axis.resolution")
    kpi_definition = field_definition("evidence.latest.kpi.total_power_mw")

    assert axis_definition is not None
    assert axis_definition.type == "string"
    assert "contains" in axis_definition.operators
    assert kpi_definition is not None
    assert kpi_definition.type == "number"
    assert "gte" in kpi_definition.operators

    fields = field_definitions(axis_keys={"codec", "fps", "custom_axis"}, kpi_keys={"total_power_mw"})
    names = [item.field for item in fields]
    assert names.index("axis.fps") < names.index("axis.codec") < names.index("axis.custom_axis")
    assert names[-1] == "evidence.latest.kpi.total_power_mw"
