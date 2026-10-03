"""Review package of a frozen architecture report: report.html + cover.html + manifest.json.

The analysis body (``rendered_html``) stays byte-identical to the stored snapshot (its sha256 is
re-checked); everything that changes after generation — review status, reviewer, notes — lives in
the cover/manifest so a saved copy can be identified offline without touching the frozen body.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from html import escape
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

MANIFEST_SCHEMA = "arch-report-package/1"


def build_manifest(meta: dict[str, Any], snapshot: dict[str, Any], rendered_html: str,
                   run_inputs: dict[str, dict[str, Any]], review_history: list[dict[str, Any]]) -> dict[str, Any]:
    body_sha = hashlib.sha256(rendered_html.encode("utf-8")).hexdigest()
    ss = snapshot.get("spec_summary") or {}
    rows = snapshot.get("scenarios") or []
    cal = snapshot.get("calibration") or []
    return {
        "schema": MANIFEST_SCHEMA,
        "report": {k: meta.get(k) for k in ("id", "title", "status", "project_ref", "target_soc_ref", "scenario_type",
                                             "engine_rev", "dvfs_table_ref", "generated_by", "generated_at")},
        "body": {"file": "report.html", "sha256": body_sha, "stored_sha256": meta.get("html_sha256"),
                 "integrity_ok": body_sha == meta.get("html_sha256")},
        "review_history": review_history,
        "runs": [{"run_id": rid, **run_inputs.get(rid, {})} for rid in meta.get("run_ids") or []],
        "predictions": [{"scenario_id": r.get("scenario_id"), "variant_id": r.get("variant_id"),
                         "prediction_id": r.get("prediction_id")} for r in rows],
        "measurements": [{"variant_id": c.get("variant_id"), "measurement_id": c.get("measurement_id"),
                          "origin": c.get("origin") or ("synthetic" if c.get("synthetic") else None)} for c in cal],
        "coverage": {
            "requested": ss.get("requested", ss.get("explored")), "evaluated": ss.get("evaluated", ss.get("explored")),
            "calc_failed": ss.get("calc_failed", len(ss.get("errors") or [])), "spec_ok": ss.get("spec_ok"),
            "spec_fail": ss.get("spec_fail"), "power_partial_model": ss.get("power_partial"),
            "not_registered": sum(1 for r in rows if not r.get("prediction_id")),
            "sw_margin_rows_omitted": max(0, sum(1 for r in rows if r.get("spec_ok")) - len(snapshot.get("sw_margin_top5") or [])),
        },
    }


def render_cover(manifest: dict[str, Any]) -> str:
    r, b, c = manifest["report"], manifest["body"], manifest["coverage"]
    rows = [("Report ID", r["id"]), ("Title", r["title"]), ("Status", r["status"]), ("Project", r["project_ref"]),
            ("Target SoC", r["target_soc_ref"]), ("Scenario type", r["scenario_type"]), ("Engine", r["engine_rev"]),
            ("DVFS table", r["dvfs_table_ref"]), ("Generated", f"{r['generated_at']} · {r['generated_by'] or '—'}"),
            ("Body sha256", f"{b['sha256']} ({'일치' if b['integrity_ok'] else '불일치 — 본문 변조 의심'})")]
    cov = " · ".join(f"{k} {v}" for k, v in c.items() if v is not None)
    reviews = "".join(
        f"<tr><td>{escape(str(x.get('at') or ''))}</td><td>{escape(str(x.get('status') or ''))}</td>"
        f"<td>{escape(str(x.get('reviewer') or '—'))}</td><td>{escape(str(x.get('note') or ''))}</td></tr>"
        for x in manifest["review_history"]) or "<tr><td colspan=4>검토 이력 없음 (draft)</td></tr>"
    runs = "".join(f"<li>{escape(str(x['run_id']))} · input {escape(str(x.get('input_hash') or '—'))[:16]}</li>"
                   for x in manifest["runs"])
    meas = ", ".join(escape(str(m["measurement_id"])) for m in manifest["measurements"] if m.get("measurement_id")) or "없음"
    return (
        "<!doctype html><html lang=ko><head><meta charset=utf-8><title>"
        f"{escape(str(r['title']))} — cover</title><style>body{{font:14px system-ui,sans-serif;margin:24px;max-width:960px}}"
        "table{border-collapse:collapse;width:100%;margin:8px 0}td,th{border:1px solid #ccc;padding:4px 8px;text-align:left}"
        "th{background:#f3f1ec;width:180px}.st{font-size:20px;font-weight:600}</style></head><body>"
        f"<p class=st>{escape(str(r['title']))} — <span>{escape(str(r['status']).upper())}</span></p>"
        "<table>" + "".join(f"<tr><th>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in rows) + "</table>"
        f"<h3>평가 coverage</h3><p>{escape(cov)}</p>"
        f"<h3>검토 이력</h3><table><tr><th>시각</th><th>상태</th><th>검토자</th><th>의견</th></tr>{reviews}</table>"
        f"<h3>재현 근거</h3><ul>{runs}</ul><p>Measurement: {meas}</p>"
        "<p><a href='report.html'>분석 본문 (report.html, snapshot 고정)</a> · manifest.json</p></body></html>"
    )


def package_zip(meta: dict[str, Any], snapshot: dict[str, Any], rendered_html: str,
                run_inputs: dict[str, dict[str, Any]], review_history: list[dict[str, Any]]) -> tuple[bytes, str]:
    manifest = build_manifest(meta, snapshot, rendered_html, run_inputs, review_history)
    buf = io.BytesIO()
    with ZipFile(buf, "w", compression=ZIP_DEFLATED) as z:
        z.writestr("report.html", rendered_html)
        z.writestr("cover.html", render_cover(manifest))
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    stamp = str(meta.get("generated_at") or "")[:16].replace(":", "").replace("-", "").replace("T", "-")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{meta.get('id')}_{meta.get('status')}_{stamp}")[:100]
    return buf.getvalue(), f"{name}.zip"
