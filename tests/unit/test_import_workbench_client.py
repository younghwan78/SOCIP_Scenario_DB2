from __future__ import annotations

import pytest

from dashboard.components.import_api_client import (
    ImportApiError,
    diff_change_rows,
    document_rows,
    import_report_rows,
    scenario_impact_rows,
    stage_import_bundle,
    validation_issue_rows,
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


def test_stage_import_bundle_posts_to_write_staging():
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response(200, {"batch_id": "b1", "status": "staged"})

    result = stage_import_bundle("http://api/api/v1", {"kind": "scenario.import_bundle"}, request)

    assert result["batch_id"] == "b1"
    assert calls[0][0] == "POST"
    assert calls[0][1] == "http://api/api/v1/write/staging"
    assert calls[0][2]["json"]["kind"] == "scenario.import_bundle"


def test_stage_import_bundle_surfaces_http_error():
    def request(method, url, **kwargs):
        return _Response(409, {"detail": "bad"}, text='{"detail":"bad"}')

    with pytest.raises(ImportApiError) as exc:
        stage_import_bundle("http://api/api/v1", {}, request)

    assert exc.value.status_code == 409
    assert "HTTP 409" in str(exc.value)
    assert exc.value.body == '{"detail":"bad"}'


def test_import_workbench_table_helpers_are_stable():
    payload = {
        "payload": {
            "documents": [
                {"kind": "project", "id": "proj-A", "metadata": {"name": "Project A"}},
                {"kind": "scenario.usecase", "id": "uc-camera", "metadata": {"name": "Camera"}},
            ],
            "import_report": {
                "messages": [
                    {"level": "warning", "code": "legacy_warn", "source": "a.yaml", "message": "warn"}
                ]
            },
        }
    }
    validation = {
        "issues": [
            {"severity": "error", "code": "bad_ref", "path": "payload.x", "message": "bad"}
        ]
    }
    diff = {
        "changes": [
            {
                "field": "documents.ip",
                "change": "modify",
                "before": {"existing_ids": ["ip-a"], "count": 1},
                "after": {
                    "ids": ["ip-a", "ip-b"],
                    "count": 2,
                    "added_ids": ["ip-b"],
                    "modified_ids": ["ip-a"],
                    "unchanged_ids": [],
                    "removed_ids": [],
                },
            }
        ],
        "impact": {
            "scenario_impacts": [
                {
                    "scenario_id": "uc-camera",
                    "operation": "create",
                    "variant_count_before": 0,
                    "variant_count_after": 2,
                    "variants_added": ["FHD30", "UHD60"],
                    "variants_removed": [],
                    "variants_updated": [],
                }
            ]
        }
    }

    assert document_rows(payload)[0]["name"] == "Project A"
    assert import_report_rows(payload["payload"]["import_report"])[0]["code"] == "legacy_warn"
    assert validation_issue_rows(validation)[0]["severity"] == "error"
    diff_row = diff_change_rows(diff)[0]
    assert diff_row["existing_count"] == 1
    assert diff_row["import_count"] == 2
    assert diff_row["added"] == "ip-b"
    assert diff_row["modified"] == "ip-a"
    assert scenario_impact_rows(diff)[0]["variants_added"] == "FHD30, UHD60"
