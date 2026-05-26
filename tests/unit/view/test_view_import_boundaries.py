from __future__ import annotations

import ast
from pathlib import Path


VIEW_SRC = Path("src/scenario_db/view")


def _imports_service(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "scenario_db.view.service":
            offenders.append(f"{path}:{node.lineno}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "scenario_db.view.service":
                    offenders.append(f"{path}:{node.lineno}")
    return offenders


def test_view_projection_modules_do_not_import_service_private_helpers():
    offenders: list[str] = []
    for path in sorted(VIEW_SRC.glob("*.py")):
        if path.name in {"__init__.py", "service.py"}:
            continue
        offenders.extend(_imports_service(path))

    assert offenders == []


def test_level2_projection_does_not_import_level1_private_helpers():
    path = VIEW_SRC / "level2_semantic.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "scenario_db.view.level1_semantic":
            private_names = [alias.name for alias in node.names if alias.name.startswith("_")]
            if private_names:
                offenders.append(f"{path}:{node.lineno} imports {', '.join(private_names)}")

    assert offenders == []


def test_view_service_does_not_import_demo_sample_data():
    path = VIEW_SRC / "service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and ".demo.sample_data" in node.module:
            offenders.append(f"{path}:{node.lineno}")

    assert offenders == []
