from __future__ import annotations

from datetime import date

import pytest
import yaml

from scenario_db import yaml_loader


@pytest.mark.parametrize("loader", [yaml.SafeLoader, getattr(yaml, "CSafeLoader", yaml.SafeLoader)])
def test_standard_types_aliases_and_merges_match_safe_loader(monkeypatch, loader):
    monkeypatch.setattr(yaml_loader, "_SAFE_LOADER", loader)
    text = '''
base: &base {enabled: yes, count: 012, ratio: 1.25, absent: null}
merged: {<<: *base, count: 7}
alias: *base
day: 2026-09-28
unicode: "센서"
literal: |
  two
  lines
quoted: "0012"
set: !!set {a: null, b: null}
binary: !!binary SGVsbG8=
'''
    actual = yaml_loader.safe_load(text)
    assert actual == yaml.safe_load(text)
    assert actual["alias"] is actual["base"]
    assert type(actual["base"]["count"]) is int
    assert type(actual["base"]["enabled"]) is bool
    assert type(actual["day"]) is date
    assert type(actual["quoted"]) is str
    assert yaml_loader.safe_load("") is None


@pytest.mark.parametrize("text", [
    '!!python/object/apply:builtins.eval ["1 + 1"]',
    '!!python/object:builtins.object {}',
    '!unknown value',
    'broken: [unclosed',
    'a: 1\n---\nb: 2',
])
@pytest.mark.parametrize("loader", [yaml.SafeLoader, getattr(yaml, "CSafeLoader", yaml.SafeLoader)])
def test_unsafe_tags_and_invalid_documents_are_rejected(monkeypatch, loader, text):
    monkeypatch.setattr(yaml_loader, "_SAFE_LOADER", loader)
    with pytest.raises(yaml.YAMLError):
        yaml_loader.safe_load(text)


def test_each_read_returns_independent_data():
    first = yaml_loader.safe_load("items: [1, 2]")
    first["items"].append(3)
    assert yaml_loader.safe_load("items: [1, 2]") == {"items": [1, 2]}
