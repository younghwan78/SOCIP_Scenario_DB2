from __future__ import annotations

from pathlib import Path


def test_level0_v2_contract_is_documented_in_read_api_contract_and_readme():
    read_contract = Path("docs/contracts/api/read-api-contract.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    resource_component = Path("dashboard/components/level0_resource_overview.py").read_text(encoding="utf-8")

    assert "level=0&mode=resource" in read_contract
    assert "level0_resource_overview" in read_contract
    assert "Scenario Resource Overview" in read_contract
    assert "Level 0 - Topology Overview" in read_contract
    assert "level=0&mode=resource" in readme
    assert "0 - Resource + Topology" in readme
    assert "Scenario Resource Overview" in resource_component
