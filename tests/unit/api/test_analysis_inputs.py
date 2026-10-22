"""Analysis input preparation through its selection/load interface."""
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from scenario_db.api.schemas.timing_budget import TimingBudgetRequest
from scenario_db.api.services import analysis_inputs, model_basis, timing_budget
from scenario_db.db.models.capability import SimConfigProfile, SocDvfsTable
from scenario_db.exceptions import NotFoundError, UnprocessableError
from scenario_db.sim.measured_timing import baseline_fingerprint
from scenario_db.sim.models import DVFSTable
from tests.unit.api.test_scenario_whatif import _graph


@pytest.fixture
def table():
    return DVFSTable.model_validate({
        "domain": "CAM",
        "levels": [{"level": 0, "speed_mhz": 1200, "voltages": {"4": 850}}],
    })


@pytest.fixture
def source(monkeypatch):
    graph = _graph()
    monkeypatch.setattr(analysis_inputs, "load_canonical_graph", lambda *a, **kw: graph)
    return graph


def request_for(graph, **kwargs):
    return TimingBudgetRequest(scenario_id=graph.scenario_id, variant_id=graph.variant_id, **kwargs)


def test_selection_resolves_profile_then_loads_real_pipeline_without_aliasing(monkeypatch, source, table):
    # Real profile merge, shape/input construction, scope checks and DVFS resolver.
    # Only the database lookup and project basis discovery are substituted.
    monkeypatch.setattr(model_basis, "apply_basis", lambda *a: None)
    profile = SimConfigProfile(id="simcfg-test", version=3, run_config={"fps": 60, "vbat": 4.0})
    db = MagicMock()
    db.get.return_value = profile
    request = request_for(source, config_profile_ref=profile.id, config={"fps": 30},
                          dvfs_tables={"CAM": table})
    original = deepcopy(request.model_dump())
    fingerprint = baseline_fingerprint(source)
    selection = analysis_inputs.resolve_analysis_selection(db, request)
    assert selection.config_profile_ref == "simcfg-test@3"
    assert selection.request.config.fps == 30
    assert selection.request.config.vbat == 4.0
    loaded = selection.load(db)
    assert loaded.graph.scenario_id == source.scenario_id
    assert loaded.tables["CAM"] == table and loaded.dvfs_table_ref is None
    selection.request.config.dvfs_overrides["CAM"] = 0
    loaded.tables["CAM"].levels.clear()
    assert request.model_dump() == original
    assert baseline_fingerprint(source) == fingerprint


@pytest.mark.parametrize("mode", ["inline", "reference", "version", "default", "disabled"])
def test_dvfs_selection_keeps_explicit_precedence_and_optional_latest_fallback(monkeypatch, source, table, mode):
    monkeypatch.setattr(analysis_inputs, "_apply_config_profile", lambda *a: None)
    row = SocDvfsTable(id="dvfs-test", soc_ref="soc-exynos2600", dvfs_version=3,
                      domains={"CAM": table.model_dump()})
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = row
    db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = row
    choices = {
        "inline": {"dvfs_tables": {"CAM": table}},
        "reference": {"dvfs_table_ref": row.id},
        "version": {"dvfs_version": 3},
        "default": {},
        "disabled": {"use_default_dvfs": False},
    }
    loaded = analysis_inputs.resolve_analysis_selection(db, request_for(source, **choices[mode])).load(db)
    assert loaded.tables == ({} if mode == "disabled" else {"CAM": table})
    assert loaded.dvfs_table_ref == (None if mode in ("inline", "disabled") else row.id)
    if mode in ("inline", "disabled"):
        db.query.assert_not_called()
    else:
        db.query.assert_called_once()


def test_explicit_missing_or_foreign_dvfs_never_falls_back(monkeypatch, source):
    monkeypatch.setattr(analysis_inputs, "_apply_config_profile", lambda *a: None)
    db = MagicMock()
    row_query = db.query.return_value.filter_by.return_value
    row_query.one_or_none.return_value = None
    selection = analysis_inputs.resolve_analysis_selection(db, request_for(source, dvfs_table_ref="dvfs-missing"))
    with pytest.raises(NotFoundError, match="DVFS table not found"):
        selection.load(db)
    row_query.order_by.assert_not_called()
    row_query.one_or_none.return_value = SocDvfsTable(id="dvfs-missing", soc_ref="soc-other", dvfs_version=1, domains={})
    with pytest.raises(UnprocessableError, match="belongs to"):
        selection.load(db)
    row_query.order_by.assert_not_called()


def test_scope_and_resolved_replay_restrictions_precede_input_execution(monkeypatch, source):
    from scenario_db.sim import sensor_projection

    monkeypatch.setattr(analysis_inputs, "_apply_config_profile", lambda *a: None)
    sensor = MagicMock()
    monkeypatch.setattr(sensor_projection, "resolve_sensor_modes", sensor)
    selection = analysis_inputs.resolve_analysis_selection(None, request_for(source, soc_ref="soc-other"))
    with pytest.raises(ValueError, match="soc_ref does not match"):
        selection.load(None)
    selection = analysis_inputs.resolve_analysis_selection(None, request_for(source))
    # Represents a replay filled after the original request was validated.
    selection.request.config = selection.request.config.model_copy(update={"timing_profile": object()})
    with pytest.raises(ValueError, match="measured timing replay"):
        selection.load(None)
    sensor.assert_not_called()


def test_invalid_projection_stops_before_sensor_resolution(monkeypatch, source):
    from scenario_db.sim import sensor_projection, sw_projection

    monkeypatch.setattr(analysis_inputs, "_apply_config_profile", lambda *a: None)
    selection = analysis_inputs.resolve_analysis_selection(None, request_for(source))
    selection.request.config = selection.request.config.model_copy(update={"sw_timing_projection": object()})
    monkeypatch.setattr(sw_projection, "verify_projection", MagicMock(side_effect=ValueError("projection drift")))
    sensor = MagicMock()
    monkeypatch.setattr(sensor_projection, "resolve_sensor_modes", sensor)
    with pytest.raises(ValueError, match="projection drift"):
        selection.load(None)
    sensor.assert_not_called()


def test_real_pipeline_limit_is_checked_before_dvfs_lookup(monkeypatch, source):
    from scenario_db.sim import service as simulation

    monkeypatch.setattr(analysis_inputs, "_apply_config_profile", lambda *a: None)
    settings = simulation.get_settings().model_copy(update={"simulation_max_workloads": 1})
    monkeypatch.setattr(simulation, "get_settings", lambda: settings)
    db = MagicMock()
    selection = analysis_inputs.resolve_analysis_selection(db, request_for(source))
    with pytest.raises(UnprocessableError, match="workloads"):
        selection.load(db)
    db.query.assert_not_called()


def test_profile_failure_remains_fatal_before_fleet_partial_failure_handling(monkeypatch):
    from scenario_db.api.schemas.timing_budget import TimingBudgetFleetRequest

    load = MagicMock()
    monkeypatch.setattr(analysis_inputs.AnalysisSelection, "load", load)
    monkeypatch.setattr(analysis_inputs, "_apply_config_profile",
                        MagicMock(side_effect=NotFoundError("profile missing")))
    with pytest.raises(NotFoundError, match="profile missing"):
        timing_budget.analyze_timing_budget_fleet(
            MagicMock(), TimingBudgetFleetRequest(scenario_id="s", variant_ids=["a", "b"]))
    load.assert_not_called()
