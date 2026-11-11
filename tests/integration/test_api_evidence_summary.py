"""Summary list contracts on the isolated PostgreSQL testcontainer."""
from __future__ import annotations

import pytest
from sqlalchemy import func, null, select
from sqlalchemy.orm import Session

from scenario_db.api.schemas.evidence import EVIDENCE_HEAVY_FIELDS
from scenario_db.db.models.evidence import Evidence

pytestmark = pytest.mark.integration


def test_evidence_summary_payloads_and_postgres_sizes(api_client, engine):
    full = api_client.get("/api/v1/evidence", params={"view": "full"}).json()
    response = api_client.get("/api/v1/evidence", params={"view": "summary"})
    assert response.status_code == 200
    summary = response.json()
    assert full["total"] == summary["total"]
    assert full["items"]
    with Session(engine) as db:
        for original, item in zip(full["items"], summary["items"], strict=True):
            assert item["id"] == original["id"]
            assert set(item["heavy"]) == set(EVIDENCE_HEAVY_FIELDS)
            for name in EVIDENCE_HEAVY_FIELDS:
                assert name not in item
                column = getattr(Evidence, name)
                size = db.scalar(select(func.pg_column_size(column)).where(Evidence.id == item["id"]))
                assert item["heavy"][name] == {
                    "present": original[name] is not None, "bytes": size or 0,
                }
            assert {k: v for k, v in original.items() if k not in EVIDENCE_HEAVY_FIELDS} == {
                k: v for k, v in item.items() if k not in ("heavy", "trace_index")
            }
            # the list views' timeline numbers, computed in SQL from the events left out of the list
            events = original["timeline_events"] or []
            numeric = [e.get("frame_index") for e in events if isinstance(e.get("frame_index"), int)]
            missing = any(not isinstance(e.get("frame_index"), int) for e in events)
            assert item["trace_index"] == {
                "events": len(events),
                "nodes": sorted({str(e["node_id"]) for e in events if e.get("node_id")}),
                "frames": len(set(numeric)),
                "frame_values": len(set(numeric)) + (1 if missing else 0),
                "layered": any(e.get("layer") for e in events),
            }


def test_evidence_full_is_still_the_default_and_detail_is_full(api_client):
    default = api_client.get("/api/v1/evidence")
    full = api_client.get("/api/v1/evidence", params={"view": "full"})
    assert default.status_code == full.status_code == 200
    assert default.json() == full.json()
    item = full.json()["items"][0]
    assert "heavy" not in item
    assert set(EVIDENCE_HEAVY_FIELDS) <= set(item)
    assert api_client.get(f"/api/v1/evidence/{item['id']}").json() == item


@pytest.mark.parametrize("filters", [
    {}, {"kind": "evidence.simulation"}, {"kind": "evidence.measurement"},
    {"scenario_ref": "uc-projecta-fhd30-recording"},
    {"variant_ref": "UHD60-HDR10-H265"}, {"project_ref": "nonexistent"},
    {"sw_version": "sw-vendor-v1.2.3"}, {"feasibility": "nonexistent"},
    {"execution_path_id": "nonexistent"},
])
@pytest.mark.parametrize("paging", [
    {"limit": 1, "offset": 0, "sort_by": "id", "sort_dir": "asc"},
    {"limit": 2, "offset": 1, "sort_by": "id", "sort_dir": "desc"},
    {"limit": 1, "offset": 9999},
])
def test_evidence_summary_filters_sort_and_paging_match_full(api_client, filters, paging):
    params = {**filters, **paging}
    full_resp = api_client.get("/api/v1/evidence", params={**params, "view": "full"})
    summary_resp = api_client.get("/api/v1/evidence", params={**params, "view": "summary"})
    assert full_resp.status_code == summary_resp.status_code == 200
    full, summary = full_resp.json(), summary_resp.json()
    assert [e["id"] for e in full.pop("items")] == [e["id"] for e in summary.pop("items")]
    assert full == summary


def test_evidence_invalid_view_is_rejected(api_client):
    assert api_client.get("/api/v1/evidence", params={"view": "invalid"}).status_code == 422


@pytest.mark.parametrize("storage", ["payload", "json-null", "sql-null"])
def test_evidence_summary_heavy_storage_cases(api_client, engine, storage):
    """Exercise every deferred field, including JSON null versus SQL NULL."""
    template = api_client.get("/api/v1/evidence", params={"limit": 1}).json()["items"][0]
    evidence_id = f"summary-contract-{storage}"
    object_fields = {"calculation_trace", "handoff_flows", "pipeline_model"}
    payloads = {
        name: (null() if storage == "sql-null" else None if storage == "json-null" else
               {"test": "payload"} if name in object_fields else [{"test": "payload"}])
        for name in EVIDENCE_HEAVY_FIELDS
    }
    with Session(engine) as db:
        try:
            db.add(Evidence(
                id=evidence_id, schema_version=template["schema_version"],
                kind="evidence.simulation", scenario_ref=template["scenario_ref"],
                variant_ref=template["variant_ref"], project_ref=template["project_ref"],
                execution_context={}, aggregation={}, kpi={}, yaml_sha256="0" * 64,
                execution_path_id=evidence_id, **payloads,
            ))
            db.commit()
            response = api_client.get("/api/v1/evidence", params={
                "view": "summary", "execution_path_id": evidence_id,
            })
            assert response.status_code == 200
            assert response.json()["total"] == 1
            item = response.json()["items"][0]
            for name in EVIDENCE_HEAVY_FIELDS:
                assert name not in item
                size = db.scalar(select(func.pg_column_size(getattr(Evidence, name)))
                                 .where(Evidence.id == evidence_id))
                assert item["heavy"][name] == {"present": storage == "payload", "bytes": size or 0}
                if storage == "sql-null":
                    assert size is None
                else:
                    assert size > 0
        finally:
            db.rollback()
            db.query(Evidence).filter(Evidence.id == evidence_id).delete(synchronize_session=False)
            db.commit()
