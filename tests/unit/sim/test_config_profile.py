from __future__ import annotations

import pytest

pytest.importorskip("networkx")
pytest.importorskip("simpy")

from scenario_db.api.schemas.simulation import SimulateRequest
from scenario_db.db.models.capability import SimConfigProfile
from scenario_db.etl.mappers.capability import upsert_sim_config_profile
from scenario_db.exceptions import NotFoundError
from scenario_db.models.capability.sim_config import (
    SimConfigProfile as PydanticSimConfigProfile,
)
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.sim.service import _apply_config_profile

RAW_PROFILE = {
    "id": "simcfg-proj-x-v1",
    "schema_version": "1.0",
    "kind": "sim.config_profile",
    "project_ref": "proj-x",
    "soc_ref": "soc-y",
    "version": 2,
    "status": "approved",
    "approved_by": "sys-eng",
    "run_config": {
        "bw_power_coeff": 100.0,
        "sw_margin": 0.10,
        "memory_rail": "VDD_MIF_L",
        "power_model": "v1-vfps",
    },
    "rail_domain_map": {"B5S4_VDDMIF_AP_L": "MIF"},
}


class _Session:
    def __init__(self):
        self.rows: dict = {}

    def get(self, model, key):
        return self.rows.get(key)

    def add(self, row):
        self.rows[row.id] = row


def _stored_profile() -> tuple[_Session, SimConfigProfile]:
    db = _Session()
    upsert_sim_config_profile(RAW_PROFILE, "sha-1", db)
    return db, db.rows["simcfg-proj-x-v1"]


def _request(**config) -> SimulateRequest:
    return SimulateRequest.model_validate(
        {
            "scenario_id": "uc-x",
            "variant_id": "v1",
            "execution_context": {
                "silicon_rev": "EVT1",
                "sw_baseline_ref": "sw-x",
                "thermal": "room",
            },
            "config_profile_ref": "simcfg-proj-x-v1",
            "config": config,
        }
    )


def test_pydantic_model_rejects_bad_status_and_version():
    with pytest.raises(ValueError):
        PydanticSimConfigProfile.model_validate({**RAW_PROFILE, "status": "final"})
    with pytest.raises(ValueError):
        PydanticSimConfigProfile.model_validate({**RAW_PROFILE, "version": 0})


def test_mapper_persists_profile_fields():
    _, row = _stored_profile()
    assert row.project_ref == "proj-x"
    assert row.version == 2
    assert row.status == "approved"
    assert row.run_config["bw_power_coeff"] == 100.0
    assert row.rail_domain_map == {"B5S4_VDDMIF_AP_L": "MIF"}


def test_profile_fills_unset_fields_and_explicit_request_wins():
    db, _ = _stored_profile()
    request = _request(sw_margin=0.2)  # explicit — must beat the profile's 0.10

    stamp = _apply_config_profile(db, request)

    assert stamp == "simcfg-proj-x-v1@2"
    assert request.config.bw_power_coeff == 100.0     # from profile
    assert request.config.memory_rail == "VDD_MIF_L"  # from profile
    assert request.config.sw_margin == 0.2            # request explicit wins
    assert request.config.vbat == 4.0                 # untouched engine default


def test_missing_profile_raises_not_found():
    with pytest.raises(NotFoundError, match="simcfg-proj-x-v1"):
        _apply_config_profile(_Session(), _request())


def test_no_profile_ref_is_a_noop():
    request = _request()
    request.config_profile_ref = None
    before = request.config.model_dump()
    assert _apply_config_profile(_Session(), request) is None
    assert request.config.model_dump() == before


def test_evidence_stamps_config_profile_ref():
    from scenario_db.sim.models import (
        IPSimParams,
        IPWorkload,
        SimulationInputs,
        SimulationRunConfig,
    )
    from scenario_db.sim.runner import build_simulation_evidence, run_simulation

    inputs = SimulationInputs(
        scenario_id="uc-x",
        variant_id="v1",
        config=SimulationRunConfig(fps=30.0, include_timeline=False),
        workloads=[
            IPWorkload(
                node_id="isp0",
                ip_ref="ip-isp",
                hw_name="ISP",
                width=1920,
                height=1080,
                fps=30.0,
                sim_params=IPSimParams(hw_name="ISP", ppc=4, unit_power_mw_mp=10),
            )
        ],
    )
    result = run_simulation(inputs, dvfs_tables={})
    evidence = build_simulation_evidence(
        result,
        execution_context=ExecutionContext(
            silicon_rev="EVT1", sw_baseline_ref="sw-x", thermal="room"
        ),
        config_profile_ref="simcfg-proj-x-v1@2",
    )
    assert evidence.run.config_profile_ref == "simcfg-proj-x-v1@2"
