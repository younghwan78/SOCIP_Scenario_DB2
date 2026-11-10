"""Timing verdict labels for frozen report rows."""

from typing import Any


def timing_unsupported(row: dict[str, Any]) -> bool:
    return row.get("verdict") == "not_applicable"


def timing_label(row: dict[str, Any], passing: str = "OK", failing: str = "FAIL") -> str:
    if timing_unsupported(row):
        return "판정 미지원"
    return passing if row.get("spec_ok") else failing


def timing_class(row: dict[str, Any]) -> str:
    if timing_unsupported(row):
        return "meta"
    return "ok" if row.get("spec_ok") else "fail"
