from __future__ import annotations

import re

from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Whitelists — 새 필드 추가 시 여기에만 등록
# ---------------------------------------------------------------------------

FEATURE_FLAGS_WHITELIST: frozenset[str] = frozenset({
    "LLC_per_ip_partition",
    "LLC_dynamic_allocation",
    "TNR_early_abort",
    "MFC_hwae",
})

IP_CATEGORIES_WHITELIST: frozenset[str] = frozenset({
    "ISP", "MFC", "DPU", "GPU", "LLC",
})

SW_COMPONENT_CATEGORIES_WHITELIST: frozenset[str] = frozenset({
    "hal", "kernel", "firmware",
})

# alphanumeric + underscore, 1-64 chars, must start with letter
_SAFE_IDENTIFIER = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,63}$')


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def validate_feature_flag_name(name: str) -> str:
    """Raises 400 if the feature flag name is not whitelisted."""
    if name not in FEATURE_FLAGS_WHITELIST:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown feature flag: {name!r}. "
                f"Allowed: {sorted(FEATURE_FLAGS_WHITELIST)}"
            ),
        )
    return name


def validate_jsonb_path(path: str) -> list[str]:
    """
    Validate a dot-separated JSONB path (e.g. 'ISP.TNR.strength').
    Each segment must match [A-Za-z][A-Za-z0-9_]{0,63}.
    Raises 400 on invalid input to prevent injection.
    """
    if not path:
        raise HTTPException(status_code=400, detail="JSONB path must not be empty")
    parts = path.split(".")
    for part in parts:
        if not _SAFE_IDENTIFIER.match(part):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid JSONB path segment: {part!r}. "
                    "Segments must start with a letter and contain only alphanumerics/underscores."
                ),
            )
    return parts


def validate_ip_category(category: str) -> str:
    if category not in IP_CATEGORIES_WHITELIST:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown IP category: {category!r}. Allowed: {sorted(IP_CATEGORIES_WHITELIST)}",
        )
    return category


def validate_sw_component_category(category: str) -> str:
    if category not in SW_COMPONENT_CATEGORIES_WHITELIST:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown SW component category: {category!r}. "
                f"Allowed: {sorted(SW_COMPONENT_CATEGORIES_WHITELIST)}"
            ),
        )
    return category
