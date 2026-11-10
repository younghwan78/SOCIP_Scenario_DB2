"""Timing verdict labels for frozen report rows."""

from typing import Any


def timing_unsupported(row: dict[str, Any]) -> bool:
    """Accept a frozen row or the engine's verdict dictionary."""
    return row.get("verdict") == "not_applicable" or row.get("status") == "not_applicable"


def timing_failed(row: dict[str, Any]) -> bool:
    return not row.get("spec_ok") and not timing_unsupported(row)


def timing_label(row: dict[str, Any], passing: str = "OK", failing: str = "FAIL") -> str:
    if timing_unsupported(row):
        return "판정 미지원"
    return passing if row.get("spec_ok") else failing


def timing_class(row: dict[str, Any]) -> str:
    if timing_unsupported(row):
        return "meta"
    return "ok" if row.get("spec_ok") else "fail"
