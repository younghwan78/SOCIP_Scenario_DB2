from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PAGE = ROOT / "dashboard" / "pages" / "6_Import_Workbench.py"


def test_import_workbench_dvfs_update_accepts_domains_file_upload() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert "st.file_uploader(" in source
    assert '"DVFS domains file"' in source
    assert 'type=["json"]' in source
    assert "dvfs_domains_json_text" in source
    assert "uploaded_domains.getvalue()" in source


def test_import_workbench_source_metadata_is_optional() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert 'st.expander("Optional source metadata", expanded=False)' in source
    assert "Guide name (optional)" in source
    assert "Source revision (optional)" in source
    assert "Source path (optional)" in source


def test_import_workbench_input_widgets_have_help_text() -> None:
    source = PAGE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    input_widgets = {"text_input", "number_input", "radio", "file_uploader", "text_area"}
    missing: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr in input_widgets
            and isinstance(func.value, ast.Name)
            and func.value.id == "st"
        ):
            continue
        if not any(keyword.arg == "help" for keyword in node.keywords):
            label = ast.unparse(node.args[0]) if node.args else func.attr
            missing.append(f"{func.attr}({label})")

    assert missing == []
