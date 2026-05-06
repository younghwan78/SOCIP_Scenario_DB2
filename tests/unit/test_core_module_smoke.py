from __future__ import annotations

import importlib


CORE_MODULE_SYMBOLS = {
    "scenario_db.view.service": ["project_level0", "project_level1", "project_level2"],
    "scenario_db.view.level0": ["project_architecture", "project_topology"],
    "scenario_db.write.service": ["stage_write", "validate_batch", "diff_batch", "apply_batch"],
    "scenario_db.legacy_import.normalize_scenario": ["convert_scenario_usecase", "convert_scenario_group_usecase"],
    "scenario_db.api.routers.explorer": ["router"],
    "scenario_db.review_gate.engine": ["run_review_gate"],
    "scenario_db.db.sql_matcher": ["find_matching_issues_sql_hybrid"],
    "scenario_db.db.jsonb_ops": ["match_rule_all_to_sql"],
    "scenario_db.db.repositories.scenario_graph": ["load_canonical_graph", "load_base_canonical_graph"],
    "scenario_db.db.repositories.variant_resolution": ["resolve_variant"],
    "scenario_db.resolver.engine": ["resolve_graph"],
    "scenario_db.etl.loader": ["load_yaml_dir"],
}


def test_core_modules_import_and_expose_expected_entrypoints():
    missing: list[str] = []
    for module_name, symbols in CORE_MODULE_SYMBOLS.items():
        module = importlib.import_module(module_name)
        for symbol in symbols:
            if not hasattr(module, symbol):
                missing.append(f"{module_name}.{symbol}")

    assert missing == []
