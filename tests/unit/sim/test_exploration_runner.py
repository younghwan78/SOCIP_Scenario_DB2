from __future__ import annotations

from scenario_db.db.models.capability import IpCatalog
from scenario_db.sim.exploration import ExplorationSweep
from scenario_db.sim.exploration_runner import run_exploration_sweep_preview
from scenario_db.sim.models import SimulationRunConfig


def test_run_exploration_sweep_preview_returns_comparison_without_persisting():
    sweep = ExplorationSweep.model_validate(
        {
            "id": "fps-sweep",
            "base_recipe": {
                "id": "preview-camera",
                "scenario_id": "uc-preview-camera",
                "variant_id": "explore",
                "project_ref": "proj-next",
                "source": {"ip_ref": "ip-sensor", "width": 1920, "height": 1080, "fps": 30, "format": "RAW"},
                "pipeline": [
                    {
                        "id": "ip0",
                        "template": "isp",
                        "ip_ref": "ip-isp-v12",
                        "inputs": [{"type": "CIN"}],
                        "outputs": [{"type": "WDMA", "port": "ISP_WDMA", "format": "YUV420"}],
                    }
                ],
            },
            "axes": [{"name": "fps", "path": "source.fps", "values": [30, 60]}],
        }
    )

    preview = run_exploration_sweep_preview(
        sweep,
        ip_catalog=_ip_catalog(),
        config=SimulationRunConfig(include_timeline=False),
    )

    assert preview.persisted is False
    assert preview.baseline_case_id == "explore-fps-30"
    assert len(preview.cases) == 2
    assert len(preview.comparison) == 2
    assert preview.comparison[0]["delta_total_power_mw"] == 0.0
    assert preview.comparison[1]["fps"] == 60.0
    assert preview.comparison[1]["total_power_mw"] > preview.comparison[0]["total_power_mw"]
    assert preview.comparison[1]["total_bw_mbs"] > preview.comparison[0]["total_bw_mbs"]


def test_run_exploration_sweep_preview_can_include_raw_results_when_requested():
    sweep = ExplorationSweep.model_validate(
        {
            "id": "single",
            "base_recipe": {
                "id": "single-camera",
                "project_ref": "proj-next",
                "source": {"ip_ref": "ip-sensor", "width": 1280, "height": 720},
                "pipeline": [{"id": "ip0", "template": "isp", "ip_ref": "ip-isp-v12"}],
            },
        }
    )

    preview = run_exploration_sweep_preview(
        sweep,
        ip_catalog=_ip_catalog(),
        include_results=True,
    )

    assert preview.cases[0].result is not None
    assert preview.cases[0].result.scenario_id == "uc-single-camera"


def _ip_catalog() -> dict[str, IpCatalog]:
    return {
        "ip-sensor": IpCatalog(
            id="ip-sensor",
            schema_version="2.2",
            category="sensor",
            hierarchy={},
            capabilities={
                "properties": {
                    "place": "rear",
                    "modes": {
                        "default": {
                            "sensor_size": [1920, 1080],
                            "sensor_fps": 30,
                            "sensor_format": "RAW",
                            "sensor_bitwidth": 12,
                            "sensor_mipi_speed": 2.5,
                        }
                    },
                }
            },
            yaml_sha256="sha",
        ),
        "ip-isp-v12": IpCatalog(
            id="ip-isp-v12",
            schema_version="2.2",
            category="camera",
            hierarchy={},
            capabilities={
                "sim": {
                    "hw_name": "ISP",
                    "ppc": 4,
                    "unit_power_mw_mp": 10,
                    "vdd": "VDD_CAM",
                    "dvfs_group": "CAM",
                }
            },
            yaml_sha256="sha",
        ),
    }
