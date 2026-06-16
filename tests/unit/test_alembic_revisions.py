from __future__ import annotations

import ast
from pathlib import Path


def test_alembic_revision_ids_are_unique():
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    revisions: dict[str, list[str]] = {}

    for path in versions.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "revision" for target in node.targets):
                continue
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                revisions.setdefault(node.value.value, []).append(path.name)

    duplicates = {
        revision: sorted(paths)
        for revision, paths in revisions.items()
        if len(paths) > 1
    }
    assert duplicates == {}
