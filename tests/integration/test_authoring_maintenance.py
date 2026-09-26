from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.db.models.evidence import Evidence
from scenario_db.etl.rename_ids import apply_renames, plan_renames
from scenario_db.etl.retire import apply_plan, plan_retirement


def test_rename_preserves_runtime_evidence_and_is_idempotent(engine):
    token = 'rename-' + uuid4().hex
    old, new = token + '-old', token + '-new'
    with Session(engine) as db:
        project = db.query(Scenario.project_ref).first()[0]
        db.add(Scenario(id=old, project_ref=project, schema_version='1.0.0',
                        metadata_={'canonical_usecase': old}, pipeline={}, yaml_sha256='source'))
        db.flush()
        db.add(ScenarioVariant(scenario_id=old, id='v', design_conditions={}))
        db.add(Evidence(id=token, scenario_ref=old, variant_ref='v', schema_version='1.0.0',
                        kind='evidence.measurement', execution_context={'sw_baseline_ref': old},
                        aggregation={}, kpi={}, yaml_sha256='original-provenance'))
        db.flush()
        plan = plan_renames(db, {old: new})
        assert 'sw_version_hint' not in plan['evidence'][0]['changes']
        apply_renames(db, plan)
        db.expire_all()
        row = db.get(Evidence, token)
        assert row.scenario_ref == new and row.sw_version_hint == new
        assert row.yaml_sha256 == 'original-provenance'
        assert db.get(ScenarioVariant, (new, 'v')) is not None
        # Canonical join keys are not scenario references. Only the source hash is invalidated.
        assert db.get(Scenario, new).metadata_['canonical_usecase'] == old
        assert plan_renames(db, {old: new}) == {}
        db.rollback()


def test_retirement_rejects_a_plan_leaving_foreign_key_orphans(engine):
    with Session(engine) as db:
        scenario = db.query(Scenario).first()
        row = dict(db.execute(select(Scenario.__table__).where(Scenario.id == scenario.id)).mappings().one())
        with pytest.raises(ValueError, match='dangling foreign key'):
            apply_plan(db, {'scenarios': [row]})
        db.rollback()
        assert db.get(Scenario, scenario.id) is not None


def test_retirement_removes_only_selected_variant_evidence(engine):
    token = 'retire-' + uuid4().hex
    with Session(engine) as db:
        project = db.query(Scenario.project_ref).first()[0]
        db.add(Scenario(id=token, project_ref=project, schema_version='1.0.0', metadata_={}, pipeline={}, yaml_sha256='test'))
        db.flush()
        for vid in ('keep', 'drop'):
            db.add(ScenarioVariant(scenario_id=token, id=vid, design_conditions={}))
            db.add(Evidence(id=token + vid, scenario_ref=token, variant_ref=vid, schema_version='1.0.0',
                            kind='evidence.measurement', execution_context={}, aggregation={}, kpi={}, yaml_sha256='test'))
        db.flush()
        spec = {'projects': set(), 'socs': set(), 'ips': [], 'scenarios': set(), 'variants': {(token, 'drop')}}
        apply_plan(db, plan_retirement(db, spec))
        db.expire_all()
        assert db.get(ScenarioVariant, (token, 'drop')) is None
        assert db.get(Evidence, token + 'drop') is None
        assert db.get(ScenarioVariant, (token, 'keep')) is not None
        assert db.get(Evidence, token + 'keep') is not None
        assert plan_retirement(db, spec) == {}
        db.rollback()


def test_rename_rejects_two_sources_without_a_canonical_target(engine):
    token = 'collision-' + uuid4().hex
    with Session(engine) as db:
        project = db.query(Scenario.project_ref).first()[0]
        for suffix in ('a', 'b'):
            db.add(Scenario(id=token + suffix, project_ref=project, schema_version='1.0.0',
                            metadata_={}, pipeline={}, yaml_sha256='test'))
        db.flush()
        with pytest.raises(ValueError, match='ambiguous rename collision'):
            plan_renames(db, {token + 'a': token + 'new', token + 'b': token + 'new'})
        assert db.get(Scenario, token + 'a') is not None
        db.rollback()
