"""Home counts and latest identifiers without loading evidence or report bodies."""
from sqlalchemy import Text, and_, case, cast, func, or_, tuple_
from scenario_db.db.models.capability import IpCatalog, SocDvfsTable
from scenario_db.db.models.definition import Project, Scenario
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.exploration import ArchExplorationRun, ArchReport, Prediction
from scenario_db.exceptions import NotFoundError


def overview(db, project_ref=None):
    project = db.get(Project, project_ref) if project_ref else None
    if project_ref and project is None:
        raise NotFoundError("project not found")
    scenario_ids = db.query(Scenario.id)
    if project_ref:
        scenario_ids = scenario_ids.filter(Scenario.project_ref == project_ref)
    p = Evidence.provenance
    explicit = p["data_origin"].astext
    origin = case((explicit.in_(["physical_capture", "synthetic", "unknown"]), explicit),
        (or_(p["collection_method"].astext.like("synthetic%"), p["device_id"].astext == "SYNTHETIC"), "synthetic"),
        (and_(func.coalesce(p["collection_method"].astext, "") != "", func.coalesce(p["device_id"].astext, "") != ""), "physical_capture"),
        else_="unknown")
    source_bucket = case((Evidence.kind == "evidence.simulation", "simulation"), else_=origin)
    evidence = (db.query(Evidence.kind, source_bucket.label("origin"), func.count(Evidence.id),
        func.count(func.distinct(tuple_(Evidence.scenario_ref, Evidence.variant_ref))))
        .filter(Evidence.scenario_ref.in_(scenario_ids)).group_by(Evidence.kind, source_bucket).all())
    counts = {"measurements": 0, "synthetic_measurements": 0, "unknown_measurements": 0}
    coverage = {"simulation": 0, "measurement": 0, "synthetic": 0, "unknown": 0, "current_prediction": 0}
    for kind, source, n, variants in evidence:
        if kind == "evidence.simulation":
            coverage["simulation"] += variants
        elif kind == "evidence.measurement":
            bucket = {"physical_capture": "measurement", "synthetic": "synthetic"}.get(source, "unknown")
            coverage[bucket] += variants
            counts[{"measurement": "measurements", "synthetic": "synthetic_measurements", "unknown": "unknown_measurements"}[bucket]] += n
    predictions = db.query(func.count(Prediction.id)).filter(Prediction.status == "current", Prediction.scenario_ref.in_(scenario_ids)).scalar()
    counts["predictions"] = coverage["current_prediction"] = predictions
    soc = ((project.metadata_ or {}).get("soc_ref") or (project.globals_ or {}).get("soc_ref")) if project else None
    ips, dvfs = db.query(IpCatalog), db.query(SocDvfsTable)
    if project_ref:
        ips = ips.filter(or_(IpCatalog.compatible_soc.is_(None), IpCatalog.compatible_soc == [], IpCatalog.compatible_soc.contains([soc])))
        dvfs = dvfs.filter(SocDvfsTable.soc_ref == soc)
    counts["ip"], counts["dvfs"] = ips.count(), dvfs.count()
    counts["dvfs_sample"] = dvfs.filter(or_(SocDvfsTable.id.ilike("%sample%"), SocDvfsTable.id.ilike("%synthetic%"),
        cast(SocDvfsTable.source, Text).ilike("%sample%"), cast(SocDvfsTable.source, Text).ilike("%synthetic%"))).count()
    runs = db.query(ArchExplorationRun)
    reports = db.query(ArchReport)
    if project_ref:
        runs, reports = runs.filter(ArchExplorationRun.project_ref == project_ref), reports.filter(ArchReport.project_ref == project_ref)
    counts.update(runs=runs.count(), reports=reports.count(), published_reports=reports.filter(ArchReport.status == "published").count())
    run = runs.with_entities(ArchExplorationRun.id, ArchExplorationRun.title, ArchExplorationRun.created_at,
        ArchExplorationRun.summary).order_by(ArchExplorationRun.created_at.desc(), ArchExplorationRun.id).first()
    report = reports.with_entities(ArchReport.id, ArchReport.status, ArchReport.generated_at).order_by(
        ArchReport.generated_at.desc(), ArchReport.id).first()
    return {"counts": counts, "coverage": coverage,
        "latest_run": {"id": run.id, "title": run.title, "created_at": run.created_at.isoformat(), "summary": run.summary} if run else None,
        "latest_report": {"id": report.id, "status": report.status, "created_at": report.generated_at.isoformat()} if report else None}
