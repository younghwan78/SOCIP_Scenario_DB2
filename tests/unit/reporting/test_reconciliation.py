from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from scenario_db.reporting.reconciliation import reconcile_artifacts


def _record(path: str, data: bytes) -> dict[str, str]:
    return {
        "artifact_id": "generation:simulation_report",
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def test_reconciliation_reports_missing_mismatched_orphan_and_invalid_paths(
    tmp_path: Path,
):
    valid = tmp_path / "prefix" / "generation" / "valid.html"
    valid.parent.mkdir(parents=True)
    valid.write_bytes(b"changed")
    orphan = tmp_path / "prefix" / "generation" / "orphan.html"
    orphan.write_bytes(b"orphan")

    findings = reconcile_artifacts(
        tmp_path,
        [
            _record("prefix/generation/valid.html", b"expected"),
            _record("prefix/generation/missing.html", b"missing"),
            _record("../escape.html", b"escape"),
        ],
    )

    assert {item.kind for item in findings} == {
        "checksum_mismatch",
        "missing_file",
        "invalid_path",
        "orphan_file",
    }


def test_reconciliation_is_dry_run_unless_staging_cleanup_is_explicit(
    tmp_path: Path,
):
    staging = tmp_path / ".scenariodb-staging-old"
    staging.mkdir()
    (staging / "partial.html").write_text("partial", encoding="utf-8")
    now = datetime.now(timezone.utc)

    dry_run = reconcile_artifacts(
        tmp_path,
        [],
        stale_after_seconds=0,
        now=now,
    )
    applied = reconcile_artifacts(
        tmp_path,
        [],
        stale_after_seconds=0,
        apply_stale_staging=True,
        now=now,
    )

    assert dry_run[0].kind == "stale_staging"
    assert dry_run[0].removed is False
    assert applied[0].removed is True
    assert not staging.exists()
