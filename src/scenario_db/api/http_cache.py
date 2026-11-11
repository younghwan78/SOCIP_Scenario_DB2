"""HTTP validators for resources that do not change once written (O-05).

A stored exploration run, one of its variants and a generated report are immutable rows: the
response carries a strong ``ETag`` (content digest) and ``Cache-Control: private, no-cache`` (the
browser revalidates every time, so a deleted or re-scoped row is never served from cache), and a
matching ``If-None-Match`` gets ``304 Not Modified`` without a body.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse

CACHE_CONTROL = "private, no-cache"


def _matches(request: Request, etag: str) -> bool:
    header = request.headers.get("if-none-match") or ""
    tags = {t.strip() for t in header.split(",") if t.strip()}
    return etag in tags or f"W/{etag}" in tags or "*" in tags


def _not_modified(etag: str) -> Response:
    return Response(status_code=304, headers={"ETag": etag, "Cache-Control": CACHE_CONTROL})


def json_response(request: Request, payload: Any) -> Response:
    """JSON with a content ETag; 304 when the client already holds it."""
    body = json.dumps(jsonable_encoder(payload), ensure_ascii=False, separators=(",", ":")).encode()
    etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
    if _matches(request, etag):
        return _not_modified(etag)
    return Response(content=body, media_type="application/json", headers={"ETag": etag, "Cache-Control": CACHE_CONTROL})


def html_response(request: Request, html: str, sha256: str | None) -> Response:
    """Stored HTML with its stored sha256 as the ETag (no re-hash per request)."""
    digest = sha256 if isinstance(sha256, str) and sha256 else hashlib.sha256(html.encode()).hexdigest()
    etag = '"' + digest[:32] + '"'
    if _matches(request, etag):
        return _not_modified(etag)
    return HTMLResponse(html, headers={"ETag": etag, "Cache-Control": CACHE_CONTROL})
