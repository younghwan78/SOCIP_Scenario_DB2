from __future__ import annotations

import hashlib
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ReconciliationFinding:
    kind: str
    path: str
    detail: str
    removed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconcile_artifacts(
    report_root: str | Path,
    artifact_records: Iterable[dict[str, Any]],
    *,
    stale_after_seconds: int = 3_600,
    apply_stale_staging: bool = False,
    now: datetime | None = None,
) -> list[ReconciliationFinding]:
    """Compare DB artifact metadata with local files.

    This is dry-run by default. Apply mode only removes stale staging
    directories, whose names are reserved by the atomic exporter.
    """

    root = Path(report_root).expanduser().resolve()
    current_time = now or datetime.now(timezone.utc)
    findings: list[ReconciliationFinding] = []
    known_files: set[Path] = set()

    for record in artifact_records:
        relative_path = record.get("path")
        if not isinstance(relative_path, str) or not relative_path:
            continue
        resolved = _safe_artifact_path(root, relative_path)
        if resolved is None:
            findings.append(
                ReconciliationFinding(
                    kind="invalid_path",
                    path=relative_path,
                    detail="Artifact path is absolute or escapes the configured report root",
                )
            )
            continue
        known_files.add(resolved)
        if not resolved.is_file():
            findings.append(
                ReconciliationFinding(
                    kind="missing_file",
                    path=relative_path,
                    detail="Artifact metadata exists but the local file is missing",
                )
            )
            continue
        expected_hash = record.get("sha256")
        if isinstance(expected_hash, str) and expected_hash:
            actual_hash = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                findings.append(
                    ReconciliationFinding(
                        kind="checksum_mismatch",
                        path=relative_path,
                        detail=f"Expected {expected_hash}, found {actual_hash}",
                    )
                )

    if root.exists():
        for file_path in root.rglob("*.html"):
            resolved_file = file_path.resolve()
            if resolved_file not in known_files and not _in_staging_dir(resolved_file, root):
                findings.append(
                    ReconciliationFinding(
                        kind="orphan_file",
                        path=resolved_file.relative_to(root).as_posix(),
                        detail="Local artifact is not referenced by database metadata",
                    )
                )

        for staging_dir in root.rglob(".scenariodb-staging-*"):
            if not staging_dir.is_dir():
                continue
            age_seconds = max(
                0.0,
                current_time.timestamp() - staging_dir.stat().st_mtime,
            )
            if age_seconds < stale_after_seconds:
                continue
            removed = False
            if apply_stale_staging:
                shutil.rmtree(staging_dir)
                removed = True
            findings.append(
                ReconciliationFinding(
                    kind="stale_staging",
                    path=staging_dir.resolve().relative_to(root).as_posix(),
                    detail=f"Staging directory is {int(age_seconds)} seconds old",
                    removed=removed,
                )
            )
    return findings


def _safe_artifact_path(root: Path, relative_path: str) -> Path | None:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def _in_staging_dir(path: Path, root: Path) -> bool:
    return any(
        part.startswith(".scenariodb-staging-")
        for part in path.relative_to(root).parts[:-1]
    )
