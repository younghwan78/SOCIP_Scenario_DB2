from __future__ import annotations

import logging
from copy import deepcopy

import pytest

from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.etl.mappers.definition import ScenarioProjectCollisionError, upsert_usecase


class _MapperQuery:
    def __init__(self, db, model, filters=None):
        self._db = db
        self._model = model
        self._filters = filters or {}

    def filter_by(self, **kwargs):
        filters = dict(self._filters)
        filters.update(kwargs)
        return _MapperQuery(self._db, self._model, filters)

    def delete(self):
        if self._model is not ScenarioVariant:
            return 0
        before = len(self._db.variants)
        self._db.variants = [
            row
            for row in self._db.variants
            if not all(getattr(row, key) == value for key, value in self._filters.items())
        ]
        return before - len(self._db.variants)

    def one_or_none(self):
        rows = self._db.scenarios.values() if self._model is Scenario else self._db.variants
        return next((row for row in rows if all(
            getattr(row, key) == value for key, value in self._filters.items()
        )), None)


class _MapperSession:
    def __init__(self):
        self.scenarios = {}
        self.variants = []
        self.info = {}

    def get(self, model, key):
        if model is Scenario:
            return self.scenarios.get(key)
        return None

    def add(self, row):
        if isinstance(row, Scenario):
            self.scenarios[row.id] = row
        elif isinstance(row, ScenarioVariant):
            self.variants.append(row)

    def flush(self):
        return None

    def query(self, model):
        return _MapperQuery(self, model)


def _usecase_doc():
    return {
        "id": "uc-import-test",
        "schema_version": "2.2",
        "kind": "scenario.usecase",
        "project_ref": "proj-A",
        "metadata": {
            "name": "Import Test",
            "category": ["camera"],
            "domain": ["camera"],
        },
        "pipeline": {
            "nodes": [
                {"id": "isp", "ip_ref": "ip-isp-v1"},
                {"id": "mfc", "ip_ref": "ip-mfc-v1"},
            ],
            "edges": [
                {"from": "isp", "to": "mfc", "type": "M2M", "buffer": "VIDEO_BUF"},
            ],
            "buffers": {"VIDEO_BUF": {"format": "NV12"}},
        },
        "variants": [
            {
                "id": "FHD30",
                "severity": "light",
                "design_conditions": {"resolution": "FHD", "fps": 30},
            }
        ],
    }


@pytest.mark.parametrize("kind", ["pipeline", "variant"])
def test_reimport_restores_original_document_after_write(kind):
    from scenario_db.write.service import _apply_pipeline_patch, _apply_variant_overlay

    db = _MapperSession()
    doc = _usecase_doc()
    upsert_usecase(doc, "sha-original", db)
    if kind == "pipeline":
        _apply_pipeline_patch(db, {"scenario_ref": doc["id"], "patch": {
            "upsert_buffers": {"VIDEO_BUF": {"format": "P010"}}
        }})
        assert db.scenarios[doc["id"]].pipeline["buffers"]["VIDEO_BUF"]["format"] == "P010"
    else:
        _apply_variant_overlay(db, {"scenario_ref": doc["id"], "variant": {
            "id": "FHD30", "design_conditions": {"fps": 60}
        }})
        assert db.variants[0].design_conditions["fps"] == 60
    assert db.scenarios[doc["id"]].yaml_sha256 != "sha-original"
    assert db.scenarios[doc["id"]].yaml_sha256 is not None
    upsert_usecase(doc, "sha-original", db)
    assert db.scenarios[doc["id"]].pipeline["buffers"]["VIDEO_BUF"]["format"] == "NV12"
    assert db.variants[0].design_conditions["fps"] == 30
    assert db.scenarios[doc["id"]].yaml_sha256 == "sha-original"


def test_upsert_usecase_persists_pipeline_and_replaces_variants():
    db = _MapperSession()
    doc = _usecase_doc()

    upsert_usecase(doc, "sha-a", db)

    row = db.scenarios["uc-import-test"]
    assert row.pipeline["edges"][0]["from"] == "isp"
    assert [variant.id for variant in db.variants] == ["FHD30"]

    updated = deepcopy(doc)
    updated["project_ref"] = "proj-B"
    updated["pipeline"]["buffers"]["VIDEO_BUF"]["format"] = "P010"
    updated["variants"] = [
        {
            "id": "UHD60",
            "severity": "heavy",
            "design_conditions": {"resolution": "UHD", "fps": 60},
        }
    ]

    db.info["scenario_project_collision_policy"] = "replace"
    upsert_usecase(updated, "sha-b", db)

    row = db.scenarios["uc-import-test"]
    assert row.project_ref == "proj-B"
    assert row.pipeline["buffers"]["VIDEO_BUF"]["format"] == "P010"
    assert [variant.id for variant in db.variants] == ["UHD60"]


def test_upsert_usecase_rejects_scenario_id_project_collision_by_default():
    db = _MapperSession()
    doc = _usecase_doc()
    upsert_usecase(doc, "sha-a", db)

    updated = deepcopy(doc)
    updated["project_ref"] = "proj-B"

    with pytest.raises(ScenarioProjectCollisionError, match="scenario id collision"):
        upsert_usecase(updated, "sha-b", db)

    assert db.scenarios["uc-import-test"].project_ref == "proj-A"
    assert [variant.id for variant in db.variants] == ["FHD30"]


def test_upsert_usecase_warns_when_collision_replacement_is_explicit(caplog):
    db = _MapperSession()
    doc = _usecase_doc()
    upsert_usecase(doc, "sha-a", db)

    updated = deepcopy(doc)
    updated["project_ref"] = "proj-B"
    db.info["scenario_project_collision_policy"] = "replace"

    with caplog.at_level(logging.WARNING, logger="scenario_db.etl.mappers.definition"):
        upsert_usecase(updated, "sha-b", db)

    assert "scenario id collision" in caplog.text
    assert "project_ref=proj-A" in caplog.text
    assert "project_ref=proj-B" in caplog.text
    assert db.scenarios["uc-import-test"].project_ref == "proj-B"


def test_upsert_usecase_can_skip_project_collision_when_explicit():
    db = _MapperSession()
    doc = _usecase_doc()
    upsert_usecase(doc, "sha-a", db)

    updated = deepcopy(doc)
    updated["project_ref"] = "proj-B"
    db.info["scenario_project_collision_policy"] = "skip"

    upsert_usecase(updated, "sha-b", db)

    assert db.scenarios["uc-import-test"].project_ref == "proj-A"
    assert [variant.id for variant in db.variants] == ["FHD30"]
