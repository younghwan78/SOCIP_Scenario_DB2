from __future__ import annotations

from copy import deepcopy

from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.etl.mappers.definition import upsert_usecase


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


class _MapperSession:
    def __init__(self):
        self.scenarios = {}
        self.variants = []

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

    upsert_usecase(updated, "sha-b", db)

    row = db.scenarios["uc-import-test"]
    assert row.project_ref == "proj-B"
    assert row.pipeline["buffers"]["VIDEO_BUF"]["format"] == "P010"
    assert [variant.id for variant in db.variants] == ["UHD60"]
