"""Return request-owned read connections before detached CPU or network work."""
from __future__ import annotations

from sqlalchemy.orm import Session

REQUEST_OWNED = "analysis_request_owned"


def release_read_connection(db: Session) -> bool:
    """Return a connection at an explicitly read-only operation boundary.

    Only explicit compute boundaries may call this helper: it must not be used
    after any write (including an autoflushed write), or inside an operation
    holding row/advisory locks. The pending-change check is an extra guard, not
    a history of flushed writes or locks. Service callers own their transactions
    unless the HTTP dependency marked the session.
    Expunge before rollback keeps already-loaded scalar/JSON inputs usable without
    an implicit refresh. Deferred attributes must be loaded before this boundary.
    """
    if not isinstance(db, Session) or db.info.get(REQUEST_OWNED) is not True:
        return False
    if (not db.is_active or not db.in_transaction() or db.in_nested_transaction()
            or db.new or db.dirty or db.deleted):
        return False
    db.expunge_all()
    db.rollback()
    return True
