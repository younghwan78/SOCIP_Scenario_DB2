from __future__ import annotations

from pathlib import Path

from scenario_db.legacy_import.read_legacy import write_yaml


def emit_hw_catalog(out_dir: Path, docs: list[dict]) -> list[Path]:
    paths: list[Path] = []
    target_dir = out_dir / "00_hw"
    for doc in docs:
        path = target_dir / f"{doc['id']}.yaml"
        write_yaml(path, doc)
        paths.append(path)
    return paths

