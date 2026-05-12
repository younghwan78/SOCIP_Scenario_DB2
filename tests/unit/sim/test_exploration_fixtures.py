from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.definition import Project
from scenario_db.models.definition.usecase import Usecase
from scenario_db.sim.exploration import (
    ExplorationRecipe,
    ExplorationSweep,
    compile_exploration_recipe,
    compile_exploration_sweep,
)
from scenario_db.sim.exploration_runner import run_exploration_sweep_preview
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.write.service import normalize_import_bundle_payload, validate_import_bundle


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "demo" / "exploration_fixtures"


@pytest.mark.parametrize("path", sorted((FIXTURE_ROOT / "recipes").glob("*.yaml")))
def test_exploration_recipe_fixtures_compile_to_valid_import_bundles(path: Path):
    recipe = ExplorationRecipe.model_validate(_read_yaml(path))

    result = compile_exploration_recipe(recipe)

    Usecase.model_validate(result.scenario)
    normalized = normalize_import_bundle_payload(result.import_bundle)
    assert validate_import_bundle(_ImportDb(), normalized) == []
    assert result.scenario["variants"][0]["node_configs"]
    for node_config in result.scenario["variants"][0]["node_configs"].values():
        assert node_config["sim"]["inherit_shape"] is True
        assert "mapping_source" in node_config["sim"]


@pytest.mark.parametrize("path", sorted((FIXTURE_ROOT / "sweeps").glob("*.yaml")))
def test_exploration_sweep_fixtures_compile_and_preview(path: Path):
    sweep = ExplorationSweep.model_validate(_read_yaml(path))

    compiled = compile_exploration_sweep(sweep)
    preview = run_exploration_sweep_preview(
        sweep,
        ip_catalog=_ip_catalog(),
        project=_ImportDb().project,
        config=SimulationRunConfig(include_timeline=False),
    )

    normalized = normalize_import_bundle_payload(compiled.import_bundle)
    assert validate_import_bundle(_ImportDb(), normalized) == []
    assert compiled.cases
    assert preview.persisted is False
    assert len(preview.cases) == len(compiled.cases)
    assert len(preview.comparison) == len(compiled.cases)
    assert preview.comparison[0]["delta_total_power_mw"] == 0.0


def test_exploration_fixtures_cover_expected_use_cases():
    recipe_names = {path.name for path in (FIXTURE_ROOT / "recipes").glob("*.yaml")}
    sweep_names = {path.name for path in (FIXTURE_ROOT / "sweeps").glob("*.yaml")}

    assert {
        "camera_otf_chain_fhd30.yaml",
        "camera_crop_scale_m2m.yaml",
        "camera_multi_output_fanout.yaml",
        "codec_display_path.yaml",
    }.issubset(recipe_names)
    assert {
        "camera_fps_format_sweep.yaml",
        "camera_scale_compression_sweep.yaml",
    }.issubset(sweep_names)


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class _Query:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter_by(self, **kwargs):
        return _Query(
            row
            for row in self._rows
            if all(getattr(row, key) == value for key, value in kwargs.items())
        )

    def one_or_none(self):
        if not self._rows:
            return None
        if len(self._rows) > 1:
            raise AssertionError("fake query expected at most one row")
        return self._rows[0]

    def all(self):
        return self._rows


class _ImportDb:
    def __init__(self):
        self.project = Project(
            id="proj-A-exynos2500",
            schema_version="2.2",
            metadata_={"name": "Project A Exynos2500", "soc_ref": "soc-exynos2500"},
            yaml_sha256="sha",
        )
        self.ips = list(_ip_catalog().values())

    def query(self, model):
        if model is Project:
            return _Query([self.project])
        if model is IpCatalog:
            return _Query(self.ips)
        return _Query([])


def _ip_catalog() -> dict[str, IpCatalog]:
    return {
        "ip-sensor-hp2-projectA": IpCatalog(
            id="ip-sensor-hp2-projectA",
            schema_version="2.2",
            category="sensor",
            hierarchy={},
            capabilities={
                "properties": {
                    "place": "rear",
                    "phy_type": "CPHY",
                    "modes": {
                        "wide_video_16_9_30": {
                            "sensor_size": [4080, 2296],
                            "sensor_fps": 30,
                            "sensor_format": "RAW_BAYER_16",
                            "sensor_bitwidth": 12,
                            "sensor_mipi_speed": 3.993,
                        }
                    },
                }
            },
            yaml_sha256="sha",
        ),
        "ip-csis-v8": _compute_ip("ip-csis-v8", "camera", "CSIS", 8, 0.21, "VDD_CAM", "CAM"),
        "ip-isp-v12": _compute_ip("ip-isp-v12", "camera", "ISP", 4, 9.92, "VDD_CAM", "CAM"),
        "ip-mfc-v14": _compute_ip("ip-mfc-v14", "codec", "MFC", 4, 1.0, "VDD_INT", "INT"),
        "ip-dpu-v9": _compute_ip("ip-dpu-v9", "display", "DPU", 4, 1.0, "VDD_INT", "INT"),
        "ip-llc-v2": IpCatalog(
            id="ip-llc-v2",
            schema_version="2.2",
            category="memory",
            hierarchy={},
            capabilities={},
            yaml_sha256="sha",
        ),
    }


def _compute_ip(
    ip_id: str,
    category: str,
    hw_name: str,
    ppc: float,
    unit_power: float,
    vdd: str,
    dvfs_group: str,
) -> IpCatalog:
    return IpCatalog(
        id=ip_id,
        schema_version="2.2",
        category=category,
        hierarchy={},
        capabilities={
            "sim": {
                "hw_name": hw_name,
                "ppc": ppc,
                "unit_power_mw_mp": unit_power,
                "vdd": vdd,
                "dvfs_group": dvfs_group,
            }
        },
        yaml_sha256="sha",
    )
