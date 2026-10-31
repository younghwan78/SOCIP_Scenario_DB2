"""Registry immutability, project isolation and concurrent trial writes on PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from scenario_db.api.schemas.timing_budget import TimingBudgetRequest
from scenario_db.api.services import model_basis as svc
from scenario_db.db.models.capability import SimConfigProfile
from scenario_db.db.models.definition import Project
from scenario_db.db.models.exploration import ModelBasis
from scenario_db.exceptions import ConflictError, UnprocessableError


@pytest.fixture
def registry(engine):
    pid = f"basis-test-{uuid4().hex}"
    cfg = f"cfg-{pid}"
    with Session(engine) as db:
        db.add(Project(id=pid, schema_version="1.0", metadata_={"soc_ref": "soc-exynos2600"}, yaml_sha256="test"))
        db.flush()
        db.add(SimConfigProfile(id=cfg, schema_version="1.0", project_ref=pid, version=1,
                                status="draft", run_config={"bw_power_mw_per_gbps": 10}, yaml_sha256="test"))
        db.commit()
    yield pid, cfg
    with Session(engine) as db:
        db.query(ModelBasis).filter_by(project_ref=pid).delete()
        db.query(SimConfigProfile).filter_by(project_ref=pid).delete()
        db.query(Project).filter_by(id=pid).delete()
        db.commit()


def create(db, registry, **kwargs):
    pid, cfg = registry
    return svc.create_basis(db, project_ref=pid, config_profile_ref=cfg, **kwargs)


def test_input_edit_requires_new_basis_even_without_version_bump(engine, registry):
    with Session(engine) as db:
        first = create(db, registry)
        assert create(db, registry)["existed"]
        prof = db.get(SimConfigProfile, registry[1])
        prof.run_config = {"bw_power_mw_per_gbps": 20}
        db.commit()
        with pytest.raises(UnprocessableError, match="inputs changed"):
            svc.activate_basis(db, first["id"])
        db.rollback()
        second = create(db, registry, parent_ref=first["id"])
        assert second["seq"] == 2 and second["content_hash"] != first["content_hash"]
        svc.activate_basis(db, second["id"])
        with pytest.raises(UnprocessableError, match="inputs changed"):
            svc.apply_basis(db, TimingBudgetRequest(scenario_id="s", variant_id="v", basis_ref=first["id"]), registry[0])


def test_reject_foreign_project_and_profile_version(engine, registry):
    pid, cfg = registry
    with Session(engine) as db:
        basis = create(db, registry)
        with pytest.raises(UnprocessableError, match="another project"):
            svc.apply_basis(db, TimingBudgetRequest(scenario_id="s", variant_id="v", basis_ref=basis["id"]), "other")
        with pytest.raises(UnprocessableError, match="version"):
            svc.create_basis(db, project_ref=pid, config_profile_ref=f"{cfg}@999")
        db.rollback()
        other = f"other-{pid}"
        db.add(Project(id=other, schema_version="1.0", metadata_={"soc_ref": "soc-exynos2600"}, yaml_sha256="test"))
        db.commit()
        try:
            with pytest.raises(UnprocessableError, match="another project"):
                svc.create_basis(db, project_ref=other, config_profile_ref=cfg)
            db.rollback()
            with pytest.raises(UnprocessableError, match="another project"):
                svc.create_basis(db, project_ref=other, parent_ref=basis["id"])
            db.rollback()
        finally:
            db.query(Project).filter_by(id=other).delete()
            db.commit()


def test_retired_basis_can_be_recreated_for_rollback(engine, registry):
    with Session(engine) as db:
        first = create(db, registry)
        svc.activate_basis(db, first["id"])
        other = svc.create_basis(db, project_ref=registry[0])
        svc.activate_basis(db, other["id"])
        rollback = create(db, registry, parent_ref=first["id"])
        assert not rollback["existed"] and rollback["id"] != first["id"]
        assert rollback["content_hash"] == first["content_hash"]
        svc.activate_basis(db, rollback["id"])


def test_detail_counts_current_basis_predictions_and_reports_catalog_drift(engine, registry):
    from scenario_db.api.services import calibration
    from scenario_db.db.models.definition import Scenario
    from scenario_db.db.models.exploration import ArchExplorationRun, Prediction
    from scenario_db.sim.arch_exploration import ENGINE_REV

    with Session(engine) as db:
        basis = create(db, registry)
        sid = f"scenario-{registry[0]}"
        db.add(Scenario(id=sid, project_ref=registry[0], schema_version="1.0", metadata_={}, pipeline={}, yaml_sha256="test"))
        db.flush()
        for label, overrides, basis_ref in (("plain", [], basis["id"]), ("override", ["config"], basis["id"]),
                                             ("other", [], "another-basis")):
            db.add(ArchExplorationRun(id=f"run-{sid}-{label}", title=label, scenario_type="test", project_ref=registry[0],
                                     spec={"input_selection": {"basis_ref": basis_ref, "basis_overrides": overrides}},
                                     variants=[], errors=[], summary={}, engine_rev=ENGINE_REV, input_hash="test"))
        db.flush()
        for label, state, variant in (("plain", "current", "v1"), ("override", "current", "v2"),
                                       ("plain", "superseded", "v1"), ("other", "current", "v3")):
            db.add(Prediction(id=f"pred-{sid}-{label}-{state}", scenario_ref=sid, variant_ref=variant,
                              project_ref=registry[0], status=state, exploration_run_ref=f"run-{sid}-{label}",
                              case_key="base", selection_rule="auto:min-power", selected_by="auto", metrics={}, input_hash="test"))
        db.flush()
        detail = svc.basis_detail(db, basis["id"])
        assert detail["inputs"]["current"] and detail["inputs"]["changed"] == []
        assert detail["predictions"] == {"current": 2, "ad_hoc": 1, "scenarios": 1}
        assert detail["profile"]["version"] == 1
        assert "freshness" not in calibration.coverage(db, sid)["v1"]["current_prediction"]
        assert "freshness" in calibration.coverage(db, sid, freshness=True)["v1"]["current_prediction"]
        profile = db.get(SimConfigProfile, registry[1])
        profile.run_config = {"bw_power_mw_per_gbps": 99}
        db.flush()
        changed = svc.basis_detail(db, basis["id"])
        assert not changed["inputs"]["current"] and changed["inputs"]["changed"] == ["config_profile"]
        assert changed["profile"]["run_config"]["bw_power_mw_per_gbps"] == 99
        assert changed["basis"]["input_stamp"] == basis["input_stamp"]


def test_concurrent_creation_deduplicates_and_activation_serializes(engine, registry):
    gate = Barrier(2)

    def new():
        with Session(engine) as db:
            gate.wait(timeout=10)
            return create(db, registry)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: new(), range(2)))
    assert results[0]["id"] == results[1]["id"]
    assert sorted(r["existed"] for r in results) == [False, True]
    with Session(engine) as db:
        second = svc.create_basis(db, project_ref=registry[0])
    gate = Barrier(2)

    def activate(bid):
        with Session(engine) as db:
            gate.wait(timeout=10)
            return svc.activate_basis(db, bid)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(activate, [results[0]["id"], second["id"]]))
    with Session(engine) as db:
        rows = db.query(ModelBasis).filter_by(project_ref=registry[0]).all()
        assert sorted(r.status for r in rows) == ["active", "retired"]


def trial(db, registry):
    basis = create(db, registry)
    row = db.get(ModelBasis, basis["id"])
    row.trial = {"trial_id": "initial", "total": 2, "items": {
        pid: {"prediction_id": pid, "scenario_id": "s", "variant_id": pid, "status": "pending"}
        for pid in ("p1", "p2")}}
    db.commit()
    return basis["id"]


def test_concurrent_trial_items_preserve_both_results(engine, registry, monkeypatch):
    from scenario_db.api.services import recompute

    with Session(engine) as db:
        bid = trial(db, registry)
    gate = Barrier(2)

    def calculate(db, pid, **kwargs):
        db.commit()  # recompute commits its run before updating the trial
        gate.wait(timeout=10)
        return {"status": "ok", "run_id": f"run-{pid}"}

    monkeypatch.setattr(recompute, "recompute_prediction", calculate)

    def run(pid):
        with Session(engine) as db:
            return svc.run_trial_item(db, bid, pid)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, ["p1", "p2"]))
    with Session(engine) as db:
        items = db.get(ModelBasis, bid).trial["items"]
        assert items["p1"]["status"] == items["p2"]["status"] == "ok"


def test_trial_restart_rejects_late_result_and_pending_promotion(engine, registry, monkeypatch):
    from scenario_db.api.services import recompute

    with Session(engine) as db:
        bid = trial(db, registry)
        with pytest.raises(UnprocessableError, match="trial first"):
            svc.promote_basis(db, bid)
        db.rollback()

        def restart(db, pid, **kwargs):
            row = db.get(ModelBasis, bid)
            row.trial = {"trial_id": "restarted", "total": 0, "items": {}}
            db.commit()
            return {"status": "ok", "run_id": "late-run"}

        monkeypatch.setattr(recompute, "recompute_prediction", restart)
        with pytest.raises(ConflictError, match="trial changed"):
            svc.run_trial_item(db, bid, "p1")
        db.rollback()
        assert db.get(ModelBasis, bid).trial["items"] == {}


def test_model_status_default_dvfs_follows_the_active_basis(engine):
    """The status line names the table an analysis uses: the active basis' DVFS, else the SoC's latest."""
    from scenario_db.api.services.arch_exploration import model_status
    from scenario_db.db.models.capability import SocDvfsTable

    tag = uuid4().hex[:8]
    pid, cfg = f"basis-dvfs-{tag}", f"cfg-basis-dvfs-{tag}"
    old, new = f"dvfs-sample-{tag}-v1", f"dvfs-{tag}-v2"
    with Session(engine) as db:
        db.add(Project(id=pid, schema_version="1.0", metadata_={"soc_ref": "soc-exynos2500"}, yaml_sha256="test"))
        top = db.query(SocDvfsTable.dvfs_version).filter_by(soc_ref="soc-exynos2500").order_by(SocDvfsTable.dvfs_version.desc()).first()
        base = (top[0] if top else 0) + 1
        for ref, ver in ((old, base), (new, base + 1)):
            db.add(SocDvfsTable(id=ref, schema_version="1.0", soc_ref="soc-exynos2500", dvfs_version=ver, domains={},
                                compatibility_scope="test", yaml_sha256="test"))
        db.flush()
        db.add(SimConfigProfile(id=cfg, schema_version="1.0", project_ref=pid, version=1,
                                status="draft", run_config={"bw_power_mw_per_gbps": 10}, yaml_sha256="test"))
        db.commit()
    try:
        with Session(engine) as db:
            assert model_status(db, project_ref=pid)["dvfs_default"] == {"ref": new, "sample": False, "source": "latest"}
            basis = svc.create_basis(db, project_ref=pid, config_profile_ref=cfg, dvfs_table_ref=old)
            svc.activate_basis(db, basis["id"])
            assert model_status(db, project_ref=pid)["dvfs_default"] == {"ref": old, "sample": True, "source": "basis"}
    finally:
        with Session(engine) as db:
            db.query(ModelBasis).filter_by(project_ref=pid).delete()
            db.query(SimConfigProfile).filter_by(project_ref=pid).delete()
            db.query(SocDvfsTable).filter(SocDvfsTable.id.in_([old, new])).delete()
            db.query(Project).filter_by(id=pid).delete()
            db.commit()
