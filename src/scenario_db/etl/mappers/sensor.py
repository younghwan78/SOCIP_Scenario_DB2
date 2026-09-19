from sqlalchemy.orm import Session
from scenario_db.db.models import sensor as rows
from scenario_db.models import sensor as models


def _upsert(raw: dict, sha256: str, session: Session, model, row_type):
    obj = model.model_validate(raw)
    row = session.get(row_type, obj.id) or row_type(id=obj.id)
    if row.yaml_sha256 == sha256:
        return
    if hasattr(obj, "board"): row.board = obj.board
    if hasattr(obj, "sensor_name"): row.sensor_name = obj.sensor_name
    row.document = obj.model_dump(exclude_none=True)
    row.yaml_sha256 = sha256
    session.add(row)


def upsert_sensor_catalog(raw, sha256, session):
    _upsert(raw, sha256, session, models.SensorCatalog, rows.SensorCatalog)


def upsert_sensor_timing(raw, sha256, session):
    _upsert(raw, sha256, session, models.SensorTimingProfile, rows.SensorTimingProfile)


def upsert_sensor_lineup(raw, sha256, session):
    _upsert(raw, sha256, session, models.SensorBoardLineup, rows.SensorBoardLineup)
