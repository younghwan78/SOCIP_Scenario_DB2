"""Check foreign keys after a maintenance operation temporarily disabled triggers."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from scenario_db.db.base import Base


def validate_foreign_keys(db: Session) -> None:
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            child = table.alias("child")
            parent = fk.column.table.alias("parent")
            source = child.c[fk.parent.name]
            target = parent.c[fk.column.name]
            orphan = db.execute(select(source).select_from(child.outerjoin(parent, source == target))
                                .where(source.is_not(None), target.is_(None)).limit(1)).first()
            if orphan:
                raise ValueError(f"dangling foreign key: {table.name}.{fk.parent.name} -> {fk.target_fullname}")
