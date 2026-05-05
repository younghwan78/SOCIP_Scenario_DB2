from __future__ import annotations

from collections.abc import Iterable

import pytest
from sqlalchemy import inspect
from sqlalchemy.schema import Column

from scenario_db.db.base import Base
import scenario_db.db.models  # noqa: F401 - register all ORM models in Base.metadata

pytestmark = pytest.mark.integration


def _normalize_type_name(type_name: str) -> str:
    normalized = type_name.upper()
    if "CHAR" in normalized or normalized in {"TEXT", "VARCHAR", "STRING"}:
        return "TEXT"
    if "JSONB" in normalized:
        return "JSONB"
    if "INTEGER" in normalized or normalized == "INT":
        return "INTEGER"
    if "BOOLEAN" in normalized or normalized == "BOOL":
        return "BOOLEAN"
    if "TIMESTAMP" in normalized or "DATETIME" in normalized:
        return "DATETIME"
    if normalized == "DATE":
        return "DATE"
    if "UUID" in normalized:
        return "UUID"
    return normalized


def _model_type(column: Column) -> str:
    return _normalize_type_name(type(column.type).__name__)


def _db_type(type_obj: object) -> str:
    return _normalize_type_name(str(type_obj))


def _format_items(items: Iterable[object]) -> str:
    return ", ".join(str(item) for item in sorted(items))


def test_alembic_head_matches_orm_metadata(engine):
    """Guard against adding ORM columns without an Alembic migration.

    The integration engine fixture starts from an empty PostgreSQL database,
    applies Alembic to head, and then loads demo data. This test compares the
    migrated database schema with SQLAlchemy Base.metadata so schema drift is
    caught before a YAML import or Write API flow depends on the missing field.
    """

    inspector = inspect(engine)
    db_tables = set(inspector.get_table_names())
    model_tables = set(Base.metadata.tables)

    ignored_db_tables = {"alembic_version"}
    assert db_tables - ignored_db_tables == model_tables, (
        "Alembic migrated tables do not match ORM metadata. "
        f"missing_in_db=[{_format_items(model_tables - db_tables)}], "
        f"unexpected_in_db=[{_format_items((db_tables - ignored_db_tables) - model_tables)}]"
    )

    for table_name in sorted(model_tables):
        model_table = Base.metadata.tables[table_name]
        db_columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        model_columns = {column.name: column for column in model_table.columns}

        assert set(db_columns) == set(model_columns), (
            f"Column drift in table {table_name}. "
            f"missing_in_db=[{_format_items(set(model_columns) - set(db_columns))}], "
            f"unexpected_in_db=[{_format_items(set(db_columns) - set(model_columns))}]"
        )

        for column_name, model_column in model_columns.items():
            db_column = db_columns[column_name]
            assert _db_type(db_column["type"]) == _model_type(model_column), (
                f"Type drift for {table_name}.{column_name}: "
                f"db={db_column['type']} model={model_column.type}"
            )
            assert db_column["nullable"] == model_column.nullable, (
                f"Nullable drift for {table_name}.{column_name}: "
                f"db={db_column['nullable']} model={model_column.nullable}"
            )

        db_pk = set(inspector.get_pk_constraint(table_name).get("constrained_columns") or [])
        model_pk = {column.name for column in model_table.primary_key.columns}
        assert db_pk == model_pk, (
            f"Primary-key drift in table {table_name}: "
            f"db=[{_format_items(db_pk)}] model=[{_format_items(model_pk)}]"
        )

        db_fks = {
            (
                tuple(fk.get("constrained_columns") or []),
                fk.get("referred_table"),
                tuple(fk.get("referred_columns") or []),
            )
            for fk in inspector.get_foreign_keys(table_name)
        }
        model_fks = {
            (
                tuple(element.parent.name for element in constraint.elements),
                constraint.elements[0].column.table.name,
                tuple(element.column.name for element in constraint.elements),
            )
            for constraint in model_table.foreign_key_constraints
        }
        assert db_fks == model_fks, (
            f"Foreign-key drift in table {table_name}: "
            f"db=[{_format_items(db_fks)}] model=[{_format_items(model_fks)}]"
        )
