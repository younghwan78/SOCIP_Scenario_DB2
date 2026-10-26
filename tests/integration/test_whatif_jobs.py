from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from scenario_db.api.schemas.scenario_whatif import WhatIfExperimentRequest, WhatIfPreviewRequest, WhatIfScope, WhatIfSweepRequest
from scenario_db.api.services import model_basis
from scenario_db.api.services.analysis_inputs import AnalysisSelection
from scenario_db.api.services import whatif_jobs as jobs
from scenario_db.api.services.compute_session import REQUEST_OWNED
from scenario_db.db.models.capability import IpCatalog, SimConfigProfile
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.exploration import ModelBasis
from scenario_db.db.models.whatif import WhatIfExperiment, WhatIfJob
from scenario_db.exceptions import ConflictError, NotFoundError
from scenario_db.sim.measured_timing import baseline_fingerprint
from tests.unit.api.test_whatif_sweep import request


@pytest.fixture
def setup(engine, monkeypatch):
    pid = "whatif-job-test-" + uuid4().hex
    with Session(engine) as db:
        db.add(Project(id=pid, schema_version="2.2", metadata_={}, globals_={}, yaml_sha256="test"))
        db.commit()
    monkeypatch.setattr(jobs.engine, "_baseline", lambda *a: {"analysis_hash": "b" * 64, "lineage": {}})
    launches = []
    monkeypatch.setattr(jobs, "_launch", lambda *a: launches.append(a))
    jobs._shutdown.clear()
    yield pid, launches
    with Session(engine) as db:
        db.query(WhatIfJob).filter_by(project_ref=pid).delete()
        db.query(Project).filter_by(id=pid).delete()
        db.commit()


def test_durable_actor_isolation_idempotency_cancel_resume(engine, setup):
    pid, launches = setup
    req = request(project_ref=pid)
    with Session(engine) as db:
        first = jobs.submit(db, req, "alice")
        again = jobs.submit(db, req, "alice")
        assert first["id"] == again["id"] and len(launches) == 1
        with pytest.raises(NotFoundError):
            jobs.get(db, first["id"], "bob")
        with pytest.raises(NotFoundError):
            jobs.cancel(db, first["id"], "bob")
        old_token = db.get(WhatIfJob, first["id"]).worker_token
        assert jobs.cancel(db, first["id"], "alice")["status"] == "cancelled"
        resumed = jobs.resume(db, first["id"], "alice")
        assert resumed["status"] == "queued" and len(launches) == 2
        assert db.get(WhatIfJob, first["id"]).worker_token != old_token
    with Session(engine) as db:
        assert jobs.get(db, first["id"], "alice")["total_cases"] == 2
        with pytest.raises(ConflictError):
            jobs.resume(db, first["id"], "alice")


def test_worker_checkpoints_and_token_fencing(engine, setup, monkeypatch):
    pid, launches = setup
    with Session(engine) as db:
        out = jobs.submit(db, request(project_ref=pid), "alice")
        token = db.get(WhatIfJob, out["id"]).worker_token
    def sweep(db, req, checkpoint, previous):
        result = {"completed_cases": 1, "rows": [{"id": "case-1"}], "cancelled": False}
        assert checkpoint(result)
        with Session(engine) as check:
            assert check.get(WhatIfJob, out["id"]).completed_cases == 1
        return {**result, "completed_cases": 2}
    monkeypatch.setattr(jobs, "run_sweep", sweep)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    jobs._run(factory, out["id"], "obsolete-token")
    jobs._run(factory, out["id"], token)
    with Session(engine) as db:
        record = jobs.get(db, out["id"], "alice")
        assert record["status"] == "completed" and record["completed_cases"] == 2


def test_expired_lease_resumable_and_errors_sanitized(engine, setup, monkeypatch):
    pid, _ = setup
    with Session(engine) as db:
        out = jobs.submit(db, request(project_ref=pid), "alice")
        row = db.get(WhatIfJob, out["id"])
        row.heartbeat_at = jobs._now() - timedelta(minutes=3)
        db.commit()
        assert jobs.get(db, row.id, "alice")["status"] == "interrupted"
        jobs.resume(db, row.id, "alice")
        token = row.worker_token
    monkeypatch.setattr(jobs, "run_sweep", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("secret-db-password")))
    jobs._run(sessionmaker(bind=engine, expire_on_commit=False), out["id"], token)
    with Session(engine) as db:
        row = jobs.get(db, out["id"], "alice")
        assert row["status"] == "failed" and "secret" not in row["error"]


def test_queue_bound_applies_to_resume(engine, setup):
    pid, _ = setup
    with Session(engine) as db:
        out = jobs.submit(db, request(project_ref=pid), "alice")
        jobs.cancel(db, out["id"], "alice")
        for i in range(16):
            db.add(WhatIfJob(id=f"{pid}-{i}", project_ref=pid, created_by="other", status="running",
                request={}, total_cases=2, completed_cases=0, cancel_requested=False,
                updated_at=jobs._now(), heartbeat_at=jobs._now()))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            jobs.resume(db, out["id"], "alice")
        assert exc.value.status_code == 429
        db.rollback()


@pytest.fixture
def real_model(engine, monkeypatch):
    """A small actual model: omitted config must inherit the project's active basis."""
    token = uuid4().hex
    pid, sid, ipid, profile = (f"job-{name}-{token}" for name in ("project", "scenario", "ip", "profile"))
    with Session(engine) as db:
        db.add(Project(id=pid, schema_version="2.2", metadata_={}, globals_={}, yaml_sha256="test"))
        db.add(IpCatalog(id=ipid, schema_version="2.2", category="isp", yaml_sha256="test",
                         capabilities={"sim": {"hw_name": "BYRP", "ppc": 4, "unit_power_mw_mp": 2.0}}))
        db.flush()
        db.add(Scenario(id=sid, project_ref=pid, schema_version="2.2", metadata_={}, yaml_sha256="test",
                        pipeline={"nodes": [{"id": "byrp", "ip_ref": ipid}], "edges": []}))
        db.add(SimConfigProfile(id=profile, project_ref=pid, schema_version="2.2", version=1, status="approved",
                               run_config={"fps": 24, "bw_power_coeff": 137.0}, yaml_sha256="test"))
        db.flush()
        db.add(ScenarioVariant(scenario_id=sid, id="v", design_conditions={"fps": 30},
                               node_configs={"byrp": {"sim": {"width": 640, "height": 480, "manual_clock_mhz": 100}}}))
        db.commit()
        basis = model_basis.create_basis(db, project_ref=pid, config_profile_ref=profile)
        model_basis.activate_basis(db, basis["id"])
    launches = []
    monkeypatch.setattr(jobs, "_launch", lambda *args: launches.append(args))
    was_shutdown = jobs._shutdown.is_set()
    jobs._shutdown.clear()
    try:
        yield WhatIfScope(project_ref=pid, scenario_id=sid, variant_id="v"), launches, basis["id"]
    finally:
        if was_shutdown:
            jobs._shutdown.set()
        with Session(engine) as db:
            db.query(WhatIfExperiment).filter_by(project_ref=pid).delete()
            db.query(WhatIfJob).filter_by(project_ref=pid).delete()
            db.query(ModelBasis).filter_by(project_ref=pid).delete()
            db.query(SimConfigProfile).filter_by(project_ref=pid).delete()
            db.query(ScenarioVariant).filter_by(scenario_id=sid).delete()
            db.query(Scenario).filter_by(id=sid).delete()
            db.query(IpCatalog).filter_by(id=ipid).delete()
            db.query(Project).filter_by(id=pid).delete()
            db.commit()


def real_request(db, scope, **settings):
    # Discover the authoritative hash using the same graph/profile resolution as
    # the UI. No baseline, computation, or sweep result is stubbed in these tests.
    base = jobs.engine._baseline(db, scope)
    return WhatIfSweepRequest(**scope.model_dump(), expected_baseline_hash=baseline_fingerprint(base["graph"]),
                              options={"frames": 4, "timeline_frames": 1, "include_whatif": False},
                              axes=[{"label": "FPS", "values": [{"target": "fps", "value": 30},
                                                                    {"target": "fps", "value": 60}]}], **settings)


@pytest.mark.parametrize("explicit_config", [None, {"bw_power_coeff": 80.0}])
def test_real_job_preserves_profile_precedence_through_queue_preview_and_save(engine, real_model, monkeypatch, explicit_config):
    scope, launches, basis_ref = real_model
    loads = []
    original_load = AnalysisSelection.load
    def record_load(selection, db):
        loads.append((selection.request.config.fps, selection.request.config.bw_power_coeff))
        return original_load(selection, db)
    monkeypatch.setattr(AnalysisSelection, "load", record_load)
    with Session(engine) as db:
        req = real_request(db, scope, **({"config": explicit_config} if explicit_config is not None else {}))
        queued = jobs.submit(db, req, "profile-reviewer")
        row = db.get(WhatIfJob, queued["id"])
        assert row.request.get("config", {}) == (explicit_config or {})
        reloaded = WhatIfSweepRequest.model_validate(row.request)
        assert reloaded.config.model_fields_set == set(explicit_config or {})
        assert reloaded.basis_ref == basis_ref
    assert len(launches) == 1
    jobs._run(*launches[0])
    with Session(engine) as db:
        finished = jobs.get(db, queued["id"], "profile-reviewer")
        assert finished["status"] == "completed", finished["error"]
        assert finished["completed_cases"] == 2
        result = finished["result"]
        assert result["baseline"]["metrics"]["fps"] == 24
        assert all(item["metrics"] is not None for item in result["rows"])
        item = result["rows"][0]
        preview = WhatIfPreviewRequest.model_validate(item["preview_request"])
        assert preview.config.model_fields_set == set(explicit_config or {})
        recalculated = jobs.engine.preview(db, preview)
        assert recalculated["condition_hash"] == item["condition_hash"]
        saved = jobs.engine.save_experiment(db, WhatIfExperimentRequest(preview_request=preview,
            expected_condition_hash=item["condition_hash"], title="Profile precedence"), "profile-reviewer")
        assert saved["preview_request"].get("config", {}) == (explicit_config or {})
        frozen_request = WhatIfPreviewRequest.model_validate(saved["preview_request"])
        assert jobs.engine.preview(db, frozen_request)["condition_hash"] == saved["condition_hash"]
    # Even an explicit code-default coefficient must win over the profile while
    # the omitted FPS continues inheriting the profile on every reload.
    assert all(fps == 24 for fps, _ in loads)
    expected_coeff = (explicit_config or {}).get("bw_power_coeff", 137.0)
    assert all(coeff == expected_coeff for _, coeff in loads[1:])


def test_real_worker_releases_baseline_connection_before_checkpoint_with_one_connection(engine, real_model, monkeypatch):
    scope, launches, _ = real_model
    bounded = create_engine(engine.url, pool_size=1, max_overflow=0, pool_timeout=0.2)
    actual_sweep = jobs.run_sweep
    checkpoints = []
    def record_sweep(db, req, *, checkpoint, previous):
        assert db.info.get(REQUEST_OWNED) is True
        def record_checkpoint(result):
            # The real baseline has issued SELECTs, but must return its connection
            # before the checkpoint opens a fresh writer session from the same pool.
            assert not db.in_transaction()
            assert bounded.pool.checkedout() == 0
            checkpoints.append(result["completed_cases"])
            return checkpoint(result)
        return actual_sweep(db, req, checkpoint=record_checkpoint, previous=previous)
    monkeypatch.setattr(jobs, "run_sweep", record_sweep)
    try:
        with Session(bounded) as db:
            queued = jobs.submit(db, real_request(db, scope), "single-connection-reviewer")
        assert len(launches) == 1
        jobs._run(*launches[0])
        with Session(bounded) as db:
            finished = jobs.get(db, queued["id"], "single-connection-reviewer")
            assert finished["status"] == "completed", finished["error"]
            assert finished["completed_cases"] == 2
        assert checkpoints == [0, 1, 2]
        assert bounded.pool.checkedout() == 0
    finally:
        bounded.dispose()
