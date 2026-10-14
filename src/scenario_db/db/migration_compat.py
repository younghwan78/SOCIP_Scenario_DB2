"""Normalize the historical 0024 label without replaying its existing tables."""
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection


def normalize_legacy_revision(connection: Connection, scripts: ScriptDirectory) -> None:
    inspector = inspect(connection)
    if not inspector.has_table("alembic_version"):
        return
    heads = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    if "0024" not in heads:
        return
    required = {"prediction_notes", "prediction_comments", "whatif_experiments"}
    if not required <= set(inspector.get_table_names()):
        raise RuntimeError("legacy 0024 schema is incomplete; restore its tables before upgrading")
    canonical = "0024_prediction_collaboration"
    if heads == {"0024"}:
        connection.execute(text("UPDATE alembic_version SET version_num = :revision WHERE version_num = '0024'"),
                           {"revision": canonical})
        return
    descendants = {canonical, *(r.revision for r in scripts.iterate_revisions("heads", canonical))}
    if not heads - {"0024"} <= descendants:
        raise RuntimeError("legacy 0024 overlaps an unrelated migration branch; inspect its revisions")
    connection.execute(text("DELETE FROM alembic_version WHERE version_num = '0024'"))
