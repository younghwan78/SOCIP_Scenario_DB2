"""Strict Exynos2600 import and resolved memory-lever projections through PostgreSQL."""
from pathlib import Path

from sqlalchemy.orm import Session

from scenario_db.api.routers.explorer import variant_matrix
from scenario_db.db.models.definition import ScenarioVariant
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.etl.loader import load_yaml_dir
from scenario_db.sim.transfers import compression_catalog, edge_port_transfers


def test_memory_levers_match_resolved_routing_and_simulation(engine):
    root = Path(__file__).resolve().parents[2]
    with engine.connect() as connection:
        tx = connection.begin()
        try:
            with Session(connection, join_transaction_mode="create_savepoint") as db:
                assert load_yaml_dir(root / "db_Exynos2600_SM-S947B", db, strict=True, validate=True).ok
                sid, vid = "uc-cam-recording-e2600", "cam-rec-r1-uhd30-vdis"

                def row():
                    result = variant_matrix(soc_ref=None, board_type=None, project_ref="proj-sm-s947b",
                                            category=None, domain=None, scenario_id=[sid], severity=None,
                                            limit=1000, offset=0, db=db)
                    return next(r for r in result.items if r.variant_id == vid)

                summary = row().memory_levers
                assert summary["llc_mb"] == 4 and len(summary["llc"]) == 4
                graph = load_canonical_graph(db, sid, vid)
                from types import SimpleNamespace

                workloads = {n["id"]: SimpleNamespace(node_id=n["id"], ip_ref=n.get("ip_ref", ""), hw_name=n["id"])
                             for n in graph.pipeline_nodes}
                transfers = edge_port_transfers(graph, workloads, comp_catalog=compression_catalog(graph.soc))
                pyramid = [t for t in transfers if "CUR_L0" in t.port]
                assert pyramid and all(t.llc_enabled and t.llc_weight == 0.6 for t in pyramid)
                variant = db.get(ScenarioVariant, (sid, vid))
                variant.routing_switch = {**(variant.routing_switch or {}), "disabled_nodes": ["mtnr"]}
                db.flush()
                assert row().memory_levers["llc"] == []
        finally:
            tx.rollback()
