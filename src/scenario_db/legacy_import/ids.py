from __future__ import annotations

import re


def project_slug(project_ref: str) -> str:
    value = project_ref.removeprefix("proj-")
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "legacy"


def catalog_id(prefix: str, name: str, project_ref: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"ip-{prefix}-{slug}-{project_slug(project_ref)}"


def ip_id(name: str, project_ref: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"ip-{slug}-{project_slug(project_ref)}"

