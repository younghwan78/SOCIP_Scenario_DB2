from scenario_db.authoring.scenario import compile_usecase, decompile_usecase, load_scenario_sources


def test_decompile_recovers_power_options_into_new_authoring_directory(tmp_path):
    options = {'knobs': {'crop': {'default': 'off', 'values': {'off': {}, 'on': {}},
                                'explore': {'iq_eval': 'required'}}}}
    original = {'id': 'uc-test', 'power_options': options,
                'variants': [{'id': 'v', 'design_conditions': {}}]}
    decompile_usecase(original, tmp_path)
    rebuilt = compile_usecase(load_scenario_sources(tmp_path))
    assert rebuilt['power_options'] == options


def test_compile_keeps_options_without_explicit_variants_in_base():
    options = {'knobs': {'crop': {'default': 'off', 'values': {'off': {}, 'on': {}}}}}
    result = compile_usecase({'base': {'id': 'uc-test'}, 'variants': [], 'knobs': options})
    assert result['power_options'] == options
