"""PostgreSQL list projections preserve scope, evidence origin and frozen details."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from scenario_db.api.services import arch_exploration as exploration
from scenario_db.api.services import calibration
from scenario_db.api.services.overview import overview
from scenario_db.api.services import scenario_whatif as whatif
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.exploration import ArchExplorationRun, ArchReport, Prediction
from scenario_db.db.models.whatif import WhatIfExperiment
from scenario_db.exceptions import NotFoundError, UnprocessableError


def scope(db):
    token = uuid4().hex
    pid, sid = f"projection-project-{token}", f"projection-scenario-{token}"
    db.add(Project(id=pid, schema_version="2.2", metadata_={"soc_ref": "soc-exynos2600"}, globals_={}, yaml_sha256="test"))
    db.flush()
    db.add(Scenario(id=sid, project_ref=pid, schema_version="2.2", metadata_={}, pipeline={}, yaml_sha256="test"))
    db.flush()
    for variant in ("v1", "v2", "v3"):
        db.add(ScenarioVariant(scenario_id=sid, id=variant, design_conditions={}, node_configs={}))
    db.flush()
    return pid, sid


def capture(db, pid, sid, suffix, variant, provenance, *, total=100, year=2026):
    row = Evidence(id=f"{sid}-{suffix}", project_ref=pid, scenario_ref=sid, variant_ref=variant,
                   schema_version="2.2", kind="evidence.measurement", yaml_sha256="test",
                   provenance=provenance, measured_at=datetime(year, 1, 1, tzinfo=timezone.utc),
                   execution_context={}, aggregation={}, kpi={"total_power_mw": total},
                   vdd_power={"RAIL": {"power_mw": total}}, timeline_events=[{"large_detail": "x" * 20000}])
    db.add(row)
    return row


def run_row(db, pid, sid, *, manifest=None):
    row = ArchExplorationRun(id=f"{sid}-run", title="Projection test", scenario_type="camera", project_ref=pid,
                             soc_ref="soc-exynos2600", spec={"manifest": {"blobs": manifest}, "config_profile_ref": "profile"},
                             variants=[{"scenario_id": sid, "variant_id": "v1", "status": "ok", "alternatives": [{"payload": "x" * 20000}],
                                        "sw_margin": {"verdict": "pass", "stages": [{"payload": "large"}]},
                                        "power_options": {"best": "selected", "status": "ok", "sets": 2,
                                                          "results": [{"key": "selected", "delta_mw": -1}, {"key": "other", "delta_mw": 2}]}},
                                       {"scenario_id": sid, "variant_id": "v2", "power_options": None}],
                             errors=[], summary={"variants": 2}, engine_rev="test", input_hash="hash")
    db.add(row)
    db.flush()
    return row


def test_physical_summary_filters_before_representative_capture(engine):
    with Session(engine) as db:
        pid, sid = scope(db)
        physical = capture(db, pid, sid, "physical", "v1", {"data_origin": "physical_capture"}, year=2024)
        capture(db, pid, sid, "unknown-newer", "v1", {}, year=2026)
        capture(db, pid, sid, "unknown-only", "v2", {})
        capture(db, pid, sid, "synthetic-only", "v3", {"collection_method": "synthetic_fixture"})
        db.flush()
        all_rows = calibration.calibration_summary(db, project_ref=pid)
        no_synthetic = calibration.calibration_summary(db, project_ref=pid, include_synthetic=False)
        physical_rows = calibration.calibration_summary(db, project_ref=pid, physical_only=True)
        assert len(all_rows["rows"]) == 3 and len(no_synthetic["rows"]) == 2
        assert [r["measurement_id"] for r in physical_rows["rows"]] == [physical.id]
        assert physical_rows["coverage"]["captures"] == 1
        assert physical_rows["scope"]["physical_only"] is True
        assert {r["origin"] for r in calibration.list_measurements(db, project_ref=pid)} == {"physical_capture", "synthetic", "unknown"}
        with pytest.raises(NotFoundError):
            calibration.calibration_summary(db, project_ref="other-project", scenario_id=sid, physical_only=True)


def test_overview_aggregates_scoped_origin_and_distinct_variant_counts(engine):
    with Session(engine) as db:
        pid, sid = scope(db)
        other_pid, other_sid = scope(db)
        capture(db, pid, sid, "p1", "v1", {"collection_method": "monitor", "device_id": "device"})
        capture(db, pid, sid, "p2", "v1", {"data_origin": "physical_capture"})
        capture(db, pid, sid, "unknown", "v2", {})
        capture(db, pid, sid, "synthetic", "v2", {"device_id": "SYNTHETIC"})
        capture(db, other_pid, other_sid, "other", "v1", {"data_origin": "physical_capture"})
        run = run_row(db, pid, sid)
        db.add(ArchReport(id=f"{sid}-report", title="Report", status="published", project_ref=pid,
                          scenario_type="camera", exploration_run_refs=[run.id], engine_rev="test",
                          snapshot={"large": "x" * 20000}, rendered_html="large", html_sha256="hash"))
        db.flush()
        queries = []
        def record(_conn, _cursor, statement, *_args):
            queries.append(statement)
        event.listen(engine, "before_cursor_execute", record)
        try:
            result = overview(db, pid)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert result["counts"]["measurements"] == 2
        assert result["coverage"]["measurement"] == 1
        assert result["counts"]["synthetic_measurements"] == result["counts"]["unknown_measurements"] == 1
        assert result["counts"]["runs"] == result["counts"]["published_reports"] == 1
        assert result["latest_run"]["id"] == run.id and result["latest_report"]["id"] == f"{sid}-report"
        # ORM count() uses an inner SELECT whose columns PostgreSQL prunes; only
        # payload-returning SELECTs must omit the large source documents.
        assert all("timeline_events" not in q and "arch_reports.snapshot" not in q
                   for q in queries if not q.lstrip().lower().startswith("select count("))
        with pytest.raises(NotFoundError):
            overview(db, "unrelated")


@pytest.mark.parametrize("manifest", [{}, None, {"digest": {"source": "blob"}}])
def test_sql_run_summary_is_equivalent_to_python_projection(engine, manifest):
    with Session(engine) as db:
        pid, sid = scope(db)
        row = run_row(db, pid, sid, manifest=manifest)
        expected = exploration.run_detail(row, view="summary")
        row_id = row.id
        db.expunge_all()
        assert exploration.run_summary(db, row_id) == expected
        detail = exploration.run_variant(db, row_id, sid, "v1")
        assert detail["detail"] and detail["alternatives"][0]["payload"]
        with pytest.raises(NotFoundError):
            exploration.run_variant(db, row_id, "other-scenario", "v1")


def test_prediction_history_cursor_is_stable_scoped_and_excludes_heavy_metrics(engine):
    with Session(engine) as db:
        pid, sid = scope(db)
        run = run_row(db, pid, sid)
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for n in range(3):
            db.add(Prediction(id=f"{sid}-p{n}", scenario_ref=sid, variant_ref="v1", project_ref=pid,
                              status="current" if n == 2 else "superseded", exploration_run_ref=run.id,
                              case_key="case", selection_rule="user", selected_by="user", created_at=stamp,
                              metrics={"power": {"total_mw": n}, "bw_mbs": n * 10, "timing": {"large": "x" * 20000}}, input_hash="hash"))
        db.flush()
        first = exploration.history_page(db, sid, "v1", limit=2)
        second = exploration.history_page(db, sid, "v1", limit=2, cursor=first["next_cursor"])
        assert [r["id"] for r in first["items"] + second["items"]] == [f"{sid}-p{n}" for n in (2, 1, 0)]
        assert second["items"][0]["total_mw"] == 0 and second["next_cursor"] is None
        assert all("metrics" not in row for row in first["items"])
        with pytest.raises(UnprocessableError):
            exploration.history_page(db, sid, "v2", cursor=first["next_cursor"])
        with pytest.raises(UnprocessableError):
            exploration.history_page(db, sid, "v1", cursor="not-a-valid-cursor")


def test_experiment_list_returns_only_metrics_and_preserves_frozen_detail(engine):
    with Session(engine) as db:
        pid, sid = scope(db)
        for visibility in ("private", "shared"):
            db.add(WhatIfExperiment(id=f"{sid}-{visibility}", project_ref=pid, scenario_ref=sid, variant_ref="v1",
                                    title="Frozen", visibility=visibility, created_by="reviewer", baseline_hash="base", condition_hash="condition",
                                    preview_request={"changes": [{"target": "fps", "value": 30}]}, normalized_condition={"fps": 30},
                                    result={"candidate": {"metrics": {"modeled_power_mw": 0}, "report": {"large": "x" * 20000}}}))
        db.flush()
        db.expunge_all()
        page = whatif.list_experiments(db, "reader", pid)
        assert page["total"] == 1 and page["items"][0]["metrics"]["modeled_power_mw"] == 0
        assert not {"result", "preview_request", "normalized_condition"} & page["items"][0].keys()
        detail = whatif.get_experiment(db, page["items"][0]["id"], "reader")
        assert detail["result"]["candidate"]["report"]["large"]
        with pytest.raises(NotFoundError):
            whatif.get_experiment(db, f"{sid}-private", "reader")
