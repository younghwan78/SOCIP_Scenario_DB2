from sqlalchemy import Column, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from scenario_db.db.base import Base

class SensorCatalog(Base):
    __tablename__ = "sensor_catalogs"
    id = Column(Text, primary_key=True)
    board = Column(Text, nullable=False, index=True)
    sensor_name = Column(Text, nullable=False, index=True)
    document = Column(JSONB, nullable=False)
    yaml_sha256 = Column(Text, nullable=False)

class SensorTimingProfile(Base):
    # Independent of SoC/project: a later project can reuse an exact sensor revision.
    __tablename__ = "sensor_timing_profiles"
    id = Column(Text, primary_key=True)
    sensor_name = Column(Text, nullable=False, index=True)
    document = Column(JSONB, nullable=False)
    yaml_sha256 = Column(Text, nullable=False)

class SensorBoardLineup(Base):
    __tablename__ = "sensor_board_lineups"
    id = Column(Text, primary_key=True)
    document = Column(JSONB, nullable=False)
    yaml_sha256 = Column(Text, nullable=False)

class ProjectSensorSelection(Base):
    __tablename__ = "project_sensor_selections"
    project_ref = Column(Text, ForeignKey("projects.id"), primary_key=True)
    slot = Column(Text, primary_key=True)
    catalog_ref = Column(Text, ForeignKey("sensor_catalogs.id"), nullable=False)
    lineup_ref = Column(Text, ForeignKey("sensor_board_lineups.id"), nullable=False)
    board_config = Column(Text, nullable=False)
