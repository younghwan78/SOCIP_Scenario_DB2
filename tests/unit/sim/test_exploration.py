from __future__ import annotations

import yaml
import pytest

from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.definition import Project
from scenario_db.models.definition.usecase import Usecase
from scenario_db.sim.exploration import (
    ExplorationRecipe,
    ExplorationSweep,
    compile_exploration_recipe,
    compile_exploration_sweep,
)
from scenario_db.write.service import normalize_import_bundle_payload, validate_import_bundle


def test_compile_exploration_recipe_emits_valid_scenario_usecase():
    recipe = ExplorationRecipe.model_validate(
        {
            "id": "next-camera-fhd30",
            "project_ref": "proj-next",
            "soc_ref": "soc-next-draft",
            "source": {
                "ip_ref": "ip-sensor-rear-s5e9965",
                "width": 4080,
                "height": 2296,
                "fps": 30,
                "format": "RAW_BAYER_16",
                "bitwidth": 12,
            },
            "mapping_profile": {
                "id": "map-next-from-2600",
                "source_project_ref": "proj-sm-s947b",
                "target_soc_ref": "soc-next-draft",
                "role_mappings": {
                    "byrp_like": {
                        "source_ip_ref": "ip-isp-s5e9965",
                        "target_ip_ref": "ip-isp-s5e9965",
                        "source_role": "byrp",
                        "target_role": "byrp",
                        "confidence": "borrowed",
                    },
                    "gdc_like": {
                        "source_ip_ref": "ip-isp-s5e9965",
                        "target_ip_ref": "ip-isp-s5e9965",
                        "source_role": "gdc_video",
                        "target_role": "gdc_video",
                        "confidence": "borrowed",
                    },
                },
            },
            "pipeline": [
                {
                    "id": "byrp0",
                    "template": "byrp_like",
                    "inputs": [{"type": "CIN"}],
                    "outputs": [{"type": "COUT"}],
                },
                {
                    "id": "gdc0",
                    "template": "gdc_like",
                    "inputs": [{"type": "RDMA"}],
                    "outputs": [
                        {
                            "type": "WDMA",
                            "port": "GDC_WDMA",
                            "format": "YUV420",
                            "compression": "COMP_SBWC_LOSSLESS",
                        }
                    ],
                    "scale": {"width": 1920, "height": 1080},
                    "output_format": "YUV420",
                },
            ],
        }
    )

    result = compile_exploration_recipe(recipe)

    Usecase.model_validate(result.scenario)
    assert result.warnings == []
    assert result.scenario["id"] == "uc-next-camera-fhd30"
    assert result.scenario["pipeline"]["edges"][0]["type"] == "OTF"
    assert result.scenario["pipeline"]["edges"][1]["type"] == "vOTF"
    assert result.scenario["pipeline"]["edges"][1]["buffer"] == "BYRP0_GDC0_BUF"
    assert result.scenario["variants"][0]["node_configs"]["gdc0"]["sim"]["scale"] == {"width": 1920, "height": 1080}
    assert result.mapping_trace[0]["mapping_confidence"] == "borrowed"
    assert result.import_bundle["kind"] == "scenario.import_bundle"


def test_compile_exploration_recipe_cli_shape_yaml_roundtrip(tmp_path):
    recipe_yaml = tmp_path / "recipe.yaml"
    recipe_yaml.write_text(
        yaml.safe_dump(
            {
                "id": "minimal",
                "project_ref": "proj-next",
                "source": {"width": 1920, "height": 1080},
                "pipeline": [{"id": "ip0", "template": "unknown", "ip_ref": "ip-isp-v12"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    recipe = ExplorationRecipe.model_validate(yaml.safe_load(recipe_yaml.read_text(encoding="utf-8")))

    result = compile_exploration_recipe(recipe)

    assert result.scenario["pipeline"]["nodes"][1]["ip_ref"] == "ip-isp-v12"
    assert result.scenario["variants"][0]["design_conditions"]["resolution_size"] == "1920x1080"


def test_compile_exploration_sweep_merges_variants_when_pipeline_is_stable():
    sweep = ExplorationSweep.model_validate(
        {
            "id": "fps-format-sweep",
            "base_recipe": {
                "id": "next-camera-fhd",
                "scenario_id": "uc-next-camera-fhd",
                "variant_id": "explore",
                "project_ref": "proj-next",
                "source": {"width": 1920, "height": 1080, "fps": 30, "format": "RAW"},
                "pipeline": [
                    {
                        "id": "ip0",
                        "template": "isp",
                        "ip_ref": "ip-isp-v12",
                        "inputs": [{"type": "CIN"}],
                        "outputs": [{"type": "COUT"}],
                    }
                ],
            },
            "axes": [
                {"name": "fps", "path": "source.fps", "values": [30, 60]},
                {"name": "fmt", "path": "source.format", "values": ["RAW", "YUV"]},
            ],
        }
    )

    result = compile_exploration_sweep(sweep)

    assert result.import_bundle["kind"] == "scenario.import_bundle"
    assert len(result.import_bundle["documents"]) == 1
    variants = result.import_bundle["documents"][0]["variants"]
    assert len(variants) == 4
    assert variants[0]["id"] == "explore-fps-30-fmt-raw"
    assert variants[-1]["design_conditions"]["fps"] == 60.0
    assert result.cases[-1]["axis_values"] == {"fps": 60.0, "fmt": "YUV"}


def test_compile_exploration_sweep_supports_labeled_object_axis_values():
    sweep = ExplorationSweep.model_validate(
        {
            "id": "output-object-sweep",
            "base_recipe": {
                "id": "next-camera-fhd",
                "scenario_id": "uc-next-camera-fhd",
                "variant_id": "explore",
                "project_ref": "proj-next",
                "source": {"width": 2400, "height": 1350, "fps": 30, "format": "RAW"},
                "pipeline": [
                    {
                        "id": "mlsc0",
                        "template": "mlsc_like",
                        "ip_ref": "ip-isp-v12",
                        "inputs": [{"type": "CIN"}],
                        "outputs": [
                            {
                                "type": "WDMA",
                                "port": "MLSC_WDMA0_L0",
                                "width": 2400,
                                "height": 1350,
                                "format": "YUV420",
                                "bitwidth": 10,
                                "compression": "COMP_OFF",
                                "comp_ratio": 1.0,
                            }
                        ],
                    }
                ],
            },
            "axes": [
                {
                    "name": "l0",
                    "path": "pipeline[0].outputs[0]",
                    "values": [
                        {
                            "label": "off",
                            "value": {
                                "type": "WDMA",
                                "port": "MLSC_WDMA0_L0",
                                "width": 2400,
                                "height": 1350,
                                "format": "YUV420",
                                "bitwidth": 10,
                                "compression": "COMP_OFF",
                                "comp_ratio": 1.0,
                            },
                        },
                        {
                            "label": "sbwc",
                            "value": {
                                "type": "WDMA",
                                "port": "MLSC_WDMA0_L0",
                                "width": 2400,
                                "height": 1350,
                                "format": "YUV420",
                                "bitwidth": 10,
                                "compression": "COMP_SBWC_LOSSLESS",
                                "comp_ratio": 0.5,
                            },
                        },
                    ],
                }
            ],
        }
    )

    result = compile_exploration_sweep(sweep)

    variants = result.import_bundle["documents"][0]["variants"]
    assert [variant["id"] for variant in variants] == ["explore-l0-off", "explore-l0-sbwc"]
    assert "comp_ratio" not in variants[0]["node_configs"]["mlsc0"]["sim"]["outputs"][0]
    assert result.cases[1]["axis_values"]["l0"]["compression"] == "COMP_SBWC_LOSSLESS"
    assert result.cases[1]["axis_values"]["l0"]["comp_ratio"] == 0.5


def test_exploration_recipe_validation_rejects_duplicate_blocks():
    with pytest.raises(ValueError, match="duplicate exploration block ids"):
        ExplorationRecipe.model_validate(
            {
                "id": "bad",
                "project_ref": "proj-next",
                "source": {"width": 1920, "height": 1080},
                "pipeline": [
                    {"id": "ip0", "template": "isp", "ip_ref": "ip-isp-v12"},
                    {"id": "ip0", "template": "gdc", "ip_ref": "ip-isp-v12"},
                ],
            }
        )


def test_compiled_import_bundle_validates_against_write_import_contract():
    recipe = ExplorationRecipe.model_validate(
        {
            "id": "write-link",
            "project_ref": "proj-next",
            "source": {"ip_ref": "ip-sensor", "width": 1920, "height": 1080},
            "pipeline": [{"id": "ip0", "template": "isp", "ip_ref": "ip-isp-v12"}],
        }
    )
    result = compile_exploration_recipe(recipe)
    normalized = normalize_import_bundle_payload(result.import_bundle)

    issues = validate_import_bundle(_ImportDb(), normalized)

    assert issues == []


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
            id="proj-next",
            schema_version="2.2",
            metadata_={"name": "Next", "soc_ref": "soc-next"},
            yaml_sha256="sha",
        )
        self.ips = [
            IpCatalog(
                id="ip-sensor",
                schema_version="2.2",
                category="sensor",
                capabilities={},
                yaml_sha256="sha",
            ),
            IpCatalog(
                id="ip-isp-v12",
                schema_version="2.2",
                category="camera",
                capabilities={},
                yaml_sha256="sha",
            ),
        ]

    def query(self, model):
        # Column queries (db.query(Model.col)) resolve to the owning class.
        model = getattr(model, "class_", model)
        if model is Project:
            return _Query([self.project])
        if model is IpCatalog:
            return _Query(self.ips)
        return _Query([])
