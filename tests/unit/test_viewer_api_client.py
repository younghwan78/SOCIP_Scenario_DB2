from __future__ import annotations

import pytest

from dashboard.components.viewer_api_client import (
    ViewerApiError,
    default_variant_id,
    list_projects,
    list_scenarios,
    list_soc_platforms,
    list_variants,
    project_label,
    scenario_label,
    soc_label,
    variant_label,
)


class _Response:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_list_scenarios_and_variants_call_read_api():
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/soc-platforms"):
            return _Response(200, {"items": [{"id": "soc-exynos2600"}]})
        if url.endswith("/projects"):
            return _Response(200, {"items": [{"id": "proj-thetis-erd", "metadata_": {"soc_ref": "soc-exynos2600"}}]})
        if url.endswith("/scenarios"):
            return _Response(200, {"items": [{"id": "uc-camera", "metadata_": {"name": "Camera"}}]})
        return _Response(200, {"items": [{"scenario_id": "uc-camera", "id": "FHD30"}]})

    socs = list_soc_platforms("http://api/api/v1", request)
    projects = list_projects("http://api/api/v1", request, soc_ref="soc-exynos2600")
    scenarios = list_scenarios("http://api/api/v1", request, project_ref="proj-thetis-erd")
    variants = list_variants("http://api/api/v1", "uc-camera", request)

    assert socs[0]["id"] == "soc-exynos2600"
    assert projects[0]["id"] == "proj-thetis-erd"
    assert scenarios[0]["id"] == "uc-camera"
    assert variants[0]["id"] == "FHD30"
    assert calls[0][0] == "GET"
    assert calls[0][1] == "http://api/api/v1/soc-platforms"
    assert calls[1][1] == "http://api/api/v1/projects"
    assert calls[1][2]["params"]["soc_ref"] == "soc-exynos2600"
    assert calls[2][1] == "http://api/api/v1/scenarios"
    assert calls[2][2]["params"]["project_ref"] == "proj-thetis-erd"
    assert calls[3][1] == "http://api/api/v1/scenarios/uc-camera/variants"


def test_list_helpers_surface_http_errors():
    def request(method, url, **kwargs):
        return _Response(500, {"detail": "bad"}, text='{"detail":"bad"}')

    with pytest.raises(ViewerApiError) as exc:
        list_scenarios("http://api/api/v1", request)

    assert exc.value.status_code == 500
    assert "HTTP 500" in str(exc.value)


def test_viewer_labels_and_default_variant_are_readable():
    scenario = {
        "id": "uc-demo-import-recording",
        "metadata_": {"name": "Demo Recording"},
        "project_ref": "proj-demo-import",
    }
    variant = {
        "id": "UHD60-HDR10-H265",
        "design_conditions": {
            "resolution": "UHD",
            "fps": 60,
            "codec": "H.265",
            "dynamic_range": "HDR10",
        },
    }
    variants = [{"id": "FHD30"}, variant]

    assert soc_label({"id": "soc-exynos2600", "process_node": "3nm"}) == "soc-exynos2600 | 3nm"
    assert project_label(
        {
            "id": "proj-thetis-erd",
            "metadata_": {
                "name": "Thetis ERD",
                "soc_ref": "soc-exynos2600",
                "board_type": "ERD",
                "board_name": "internal-dev",
            },
        }
    ) == "proj-thetis-erd | Thetis ERD | soc=soc-exynos2600 | board=ERD | internal-dev"
    assert scenario_label(scenario) == "uc-demo-import-recording | Demo Recording | project=proj-demo-import"
    assert variant_label(variant) == "UHD60-HDR10-H265 | resolution=UHD, fps=60, codec=H.265, dynamic_range=HDR10"
    assert default_variant_id(variants, "UHD60-HDR10-H265") == "UHD60-HDR10-H265"
    assert default_variant_id([], "missing") == ""
