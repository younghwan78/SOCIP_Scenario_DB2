"""CLI transport for the authenticated camera preview/commit API."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload, allow_nan=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=60) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(
            f"Camera import API returned HTTP {exc.code}; check credentials, references and evidence ID conflicts."
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            "Camera import API connection failed. If commit was sent, its outcome may be unknown; rerun the identical input to check safely."
        ) from exc
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError("Camera import API returned an invalid JSON response.") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Camera import API returned an invalid response object.")
    return result


def commit_via_api(evidence, api_base: str) -> dict:
    parsed = urlsplit(api_base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "--api-base must be an HTTP(S) API root without credentials/query/fragment"
        )
    key_id = os.environ.get("SCENARIODB_API_KEY_ID", "").strip()
    secret = os.environ.get("SCENARIODB_API_KEY", "").strip()
    if bool(key_id) != bool(secret):
        raise ValueError("Set both SCENARIODB_API_KEY_ID and SCENARIODB_API_KEY")
    headers = {"X-ScenarioDB-Key-Id": key_id, "X-ScenarioDB-API-Key": secret} if key_id else {}
    payload = {"evidence": evidence.model_dump(mode="json", exclude_none=True)}
    base = api_base.rstrip("/")
    preview = _post_json(base + "/profiling/import/preview", payload, headers)
    digest = preview.get("sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise RuntimeError(
            "Camera preview did not return a valid content hash; commit was not sent."
        )
    result = _post_json(
        base + "/profiling/import/commit", {**payload, "expected_hash": digest}, headers
    )
    if (
        result.get("id") != str(evidence.id)
        or result.get("sha256") != digest
        or result.get("status") not in {"created", "unchanged"}
    ):
        raise RuntimeError(
            "Camera commit response could not be verified; rerun identical input to check safely."
        )
    return {**result, "persisted": True}
