"""PostgreSQL frozen experiments honor visibility and never promote a prediction."""
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from scenario_db.api.schemas.scenario_whatif import WhatIfExperimentRequest
from scenario_db.api.services import scenario_whatif as service
from scenario_db.db.models.definition import Project, Scenario
from scenario_db.db.models.exploration import Prediction
from scenario_db.db.models.whatif import WhatIfExperiment
from scenario_db.exceptions import ConflictError, NotFoundError


def test_frozen_private_shared_records_server_recalculation_and_drift(engine, monkeypatch):
    token = uuid4().hex
    pid, sid = f"whatif-project-{token}", f"whatif-scenario-{token}"
    condition_hash = "b" * 64
    baseline_hash = "a" * 64
    calls = []

    def authoritative(db, request):
        calls.append(request.model_dump())
        return {"baseline_hash": baseline_hash, "condition_hash": condition_hash,
                "normalized_condition": {"changes": [{"target": "fps", "value": 60}]},
                "candidate": {"metrics": {"modeled_power_mw": 234, "total_power_mw": None}}}

    monkeypatch.setattr(service, "preview", authoritative)
    with Session(engine) as db:
        db.add(Project(id=pid, schema_version="2.2", metadata_={"soc_ref": "soc-exynos2600"}, globals_={}, yaml_sha256="test"))
        db.flush()
        db.add(Scenario(id=sid, project_ref=pid, schema_version="2.2", metadata_={}, pipeline={}, yaml_sha256="test"))
        db.commit()
    condition = {"project_ref": pid, "scenario_id": sid, "variant_id": "v1",
                 "expected_baseline_hash": baseline_hash, "changes": [{"target": "fps", "value": 60}]}
    payload = dict(preview_request=condition, expected_condition_hash=condition_hash, title="FPS review",
                   purpose="test cadence", description="Review the fixed runtime assumption", assumptions="SW fixed", conclusion="Needs measurement")
    try:
        with Session(engine) as db:
            private = service.save_experiment(db, WhatIfExperimentRequest(**payload), "alice")
            shared = service.save_experiment(db, WhatIfExperimentRequest(**payload, visibility="shared"), "alice")
            assert len(calls) == 2
            assert private["result"]["candidate"]["metrics"]["modeled_power_mw"] == 234
            assert service.list_experiments(db, "alice", pid)["total"] == 2
            bob = service.list_experiments(db, "bob", pid)
            assert bob["total"] == 1 and bob["items"][0]["id"] == shared["id"]
            assert service.get_experiment(db, shared["id"], "bob")["description"] == payload["description"]
            with pytest.raises(NotFoundError):
                service.get_experiment(db, private["id"], "bob")
            page = service.list_experiments(db, "alice", pid, limit=1)
            assert len(page["items"]) == 1 and page["has_next"]
            assert db.query(Prediction).filter_by(scenario_ref=sid).count() == 0
            condition_hash = "c" * 64
            with pytest.raises(ConflictError):
                service.save_experiment(db, WhatIfExperimentRequest(**payload), "alice")
            assert db.query(WhatIfExperiment).filter_by(project_ref=pid).count() == 2
            # Saved numbers remain frozen when the model recalculation later changes.
            assert service.get_experiment(db, private["id"], "alice")["condition_hash"] == "b" * 64
    finally:
        with Session(engine) as db:
            db.query(WhatIfExperiment).filter_by(project_ref=pid).delete()
            db.query(Scenario).filter_by(id=sid).delete()
            db.query(Project).filter_by(id=pid).delete()
            db.commit()
