from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from scenario_db.api.schemas.arch_exploration import ArchExplorationRunRequest
from scenario_db.api.services import arch_exploration as svc
from scenario_db.api.services import exploration_jobs as jobs
from scenario_db.api.services import whatif_jobs
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.whatif import WhatIfJob
from scenario_db.exceptions import ConflictError, NotFoundError, UnprocessableError


@pytest.fixture
def scope(engine, monkeypatch):
    token = uuid4().hex
    pid, sid = f"proj-explore-job-{token}", f"uc-explore-job-{token}"
    with Session(engine) as db:
        db.add(Project(id=pid, schema_version="2.2", metadata_={}, globals_={}, yaml_sha256="test"))
        db.flush()
        db.add(Scenario(id=sid, project_ref=pid, schema_version="1.0.0", metadata_={"category": ["camera"]},
                        pipeline={}, yaml_sha256="test"))
        db.flush()
        for v in ("v1", "v2", "v3"):
            db.add(ScenarioVariant(scenario_id=sid, id=v, design_conditions={}))
        db.commit()
    launches = []
    monkeypatch.setattr(jobs, "_launch", lambda *a: launches.append(a))
    jobs._shutdown.clear()
    yield ArchExplorationRunRequest(project_ref=pid, scenario_ids=[sid]), launches
    with Session(engine) as db:
        db.query(WhatIfJob).filter_by(project_ref=pid).delete()
        db.query(ScenarioVariant).filter_by(scenario_id=sid).delete()
        db.query(Scenario).filter_by(id=sid).delete()
        db.query(Project).filter_by(id=pid).delete()
        db.commit()


def test_submit_isolation_cancel_resume(engine, scope):
    request, launches = scope
    with Session(engine) as db:
        job = jobs.submit(db, request, "alice")
        assert job["id"].startswith("explore-job-") and job["status"] == "queued"
        assert job["total_variants"] == 3 and len(launches) == 1
        with pytest.raises(NotFoundError):
            jobs.get(db, job["id"], "bob")
        # the shared table never serves an exploration job as a What-if sweep (and vice versa)
        with pytest.raises(NotFoundError):
            whatif_jobs.get(db, job["id"], "alice")
        with pytest.raises(NotFoundError):
            jobs.get(db, "whatif-job-" + "0" * 16, "alice")
        old = db.get(WhatIfJob, job["id"]).worker_token
        assert jobs.cancel(db, job["id"], "alice")["status"] == "cancelled"
        again = jobs.resume(db, job["id"], "alice")
        assert again["status"] == "queued" and again["completed_variants"] == 0 and len(launches) == 2
        assert db.get(WhatIfJob, job["id"]).worker_token != old
        with pytest.raises(ConflictError):
            jobs.resume(db, job["id"], "alice")
        with pytest.raises(UnprocessableError, match="max_variants"):
            jobs.submit(db, request.model_copy(update={"max_variants": 2}), "alice")
        with pytest.raises(UnprocessableError, match="apply_options"):
            jobs.submit(db, request.model_copy(update={"apply_options": ["knob:x=y"]}), "alice")


def test_worker_progress_completion_and_fencing(engine, scope, monkeypatch):
    request, _ = scope
    with Session(engine) as db:
        job = jobs.submit(db, request, "alice")
        token = db.get(WhatIfJob, job["id"]).worker_token
    seen = []

    def run(db, req, user, *, release_connection, progress, parallel):
        assert parallel and user == "alice" and req.scenario_ids == request.scenario_ids
        for done, variant in enumerate((None, "v1", "v2", "v3")):
            assert progress(done, 3, variant)
            with Session(engine) as check:
                seen.append(check.get(WhatIfJob, job["id"]).status)
        return {"id": "EXP-test", "summary": {"variants": 2, "errors": 1}}
    monkeypatch.setattr(svc, "run_exploration", run)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    jobs._run(factory, job["id"], "obsolete-token")
    with Session(engine) as db:
        assert jobs.get(db, job["id"], "alice")["status"] == "queued"
    jobs._run(factory, job["id"], token)
    assert set(seen) == {"running"}
    with Session(engine) as db:
        out = jobs.get(db, job["id"], "alice")
    assert out["status"] == "completed" and out["run_id"] == "EXP-test"
    assert (out["completed_variants"], out["failed_variants"]) == (3, 1)


def test_cancel_request_stops_the_worker(engine, scope, monkeypatch):
    request, _ = scope
    with Session(engine) as db:
        job = jobs.submit(db, request, "alice")
        token = db.get(WhatIfJob, job["id"]).worker_token

    def run(db, req, user, *, release_connection, progress, parallel):
        assert progress(0, 3, None)
        with Session(engine) as other:
            jobs.cancel(other, job["id"], "alice")
        if not progress(1, 3, "v1"):
            raise svc.ExplorationCancelled
        raise AssertionError("cancel was not seen")
    monkeypatch.setattr(svc, "run_exploration", run)
    jobs._run(sessionmaker(bind=engine, expire_on_commit=False), job["id"], token)
    with Session(engine) as db:
        out = jobs.get(db, job["id"], "alice")
    assert out["status"] == "cancelled" and out["run_id"] is None and out["resumable"]


def test_domain_errors_are_reported_and_others_are_hidden(engine, scope, monkeypatch):
    request, _ = scope
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    for exc, text in ((UnprocessableError("every variant failed (3)"), "every variant failed (3)"),
                      (RuntimeError("psycopg internals"), "탐색 실패")):
        with Session(engine) as db:
            job = jobs.submit(db, request, "alice")
            token = db.get(WhatIfJob, job["id"]).worker_token

        def run(*a, exc=exc, **k):
            raise exc
        monkeypatch.setattr(svc, "run_exploration", run)
        jobs._run(factory, job["id"], token)
        with Session(engine) as db:
            out = jobs.get(db, job["id"], "alice")
        assert out["status"] == "failed" and out["error"].startswith(text) and out["resumable"]
