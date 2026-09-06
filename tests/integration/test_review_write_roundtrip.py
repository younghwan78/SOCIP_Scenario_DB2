import pytest
from sqlalchemy.orm import Session

from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.etl.mappers.definition import upsert_usecase
from scenario_db.write.service import _apply_pipeline_patch, _apply_variant_overlay


@pytest.mark.parametrize("kind", ["pipeline", "variant"])
def test_postgres_reimport_restores_data_after_write(engine, kind):
    doc = {
        "id": "uc-review-roundtrip", "schema_version": "2.2", "kind": "scenario.usecase",
        "project_ref": "proj-review-roundtrip",
        "metadata": {"name": "Roundtrip", "category": ["camera"], "domain": ["camera"]},
        "pipeline": {"nodes": [], "edges": [], "buffers": {"VIDEO": {"format": "NV12"}}},
        "variants": [{"id": "v1", "severity": "light", "design_conditions": {"fps": 30}}],
    }
    with Session(engine) as db:
        db.add(Project(id=doc["project_ref"], schema_version="2.2", metadata_={}, yaml_sha256="original"))
        db.flush()
        upsert_usecase(doc, "original", db)
        if kind == "pipeline":
            _apply_pipeline_patch(db, {"scenario_ref": doc["id"], "patch": {
                "upsert_buffers": {"VIDEO": {"format": "P010"}}
            }})
        else:
            _apply_variant_overlay(db, {"scenario_ref": doc["id"], "variant": {
                "id": "v1", "design_conditions": {"fps": 60}
            }})
        db.expire_all()
        assert db.get(Scenario, doc["id"]).yaml_sha256 != "original"
        upsert_usecase(doc, "original", db)
        db.flush()
        db.expire_all()
        assert db.get(Scenario, doc["id"]).pipeline["buffers"]["VIDEO"]["format"] == "NV12"
        variant = db.query(ScenarioVariant).filter_by(scenario_id=doc["id"], id="v1").one()
        assert variant.design_conditions["fps"] == 30
        db.rollback()
