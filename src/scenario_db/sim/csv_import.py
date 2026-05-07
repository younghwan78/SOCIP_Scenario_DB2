from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class LegacySimModeRow:
    project: str | None
    hw_name: str
    mode: str
    unit_power_mw_mp: float
    idc: float
    ppc: float
    vdd: str | None
    dvfs_group: str | None


def load_legacy_sim_info_csv(path: str | Path) -> list[LegacySimModeRow]:
    """Load legacy project*_info.csv rows into mode-specific simulation params."""

    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return []

    project = _project_name(rows[0])
    header_index = _find_header_index(rows)
    if header_index is None:
        raise ValueError("legacy sim info CSV header row was not found")

    header = [_normalize_header(cell) for cell in rows[header_index]]
    index = {name: pos for pos, name in enumerate(header) if name}
    required = {"name", "mode", "unit_power", "idc", "ppc", "vdd", "dvfs"}
    missing = sorted(required - set(index))
    if missing:
        raise ValueError(f"legacy sim info CSV is missing columns: {', '.join(missing)}")

    parsed: list[LegacySimModeRow] = []
    for row in rows[header_index + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        hw_name = _cell(row, index["name"])
        mode = _cell(row, index["mode"])
        if not hw_name or not mode:
            continue
        parsed.append(
            LegacySimModeRow(
                project=project,
                hw_name=hw_name,
                mode=mode,
                unit_power_mw_mp=_float_cell(row, index["unit_power"]),
                idc=_float_cell(row, index["idc"]),
                ppc=_float_cell(row, index["ppc"]),
                vdd=_optional_cell(row, index["vdd"]),
                dvfs_group=_optional_cell(row, index["dvfs"]),
            )
        )
    return parsed


def build_sim_block(rows: list[LegacySimModeRow], hw_name: str) -> dict[str, Any]:
    """Build an IpCatalog capabilities.sim block for one legacy HW name."""

    matches = [row for row in rows if row.hw_name.upper() == hw_name.upper()]
    if not matches:
        raise ValueError(f"legacy sim info CSV has no rows for HW name: {hw_name}")

    canonical_name = matches[0].hw_name
    block: dict[str, Any] = {
        "hw_name": canonical_name,
        "source": "legacy_project_info_csv",
        "modes": {},
    }
    if matches[0].project:
        block["source_project"] = matches[0].project
    for row in matches:
        block["modes"][row.mode] = {
            "unit_power_mw_mp": row.unit_power_mw_mp,
            "idc": row.idc,
            "ppc": row.ppc,
            "vdd": row.vdd,
            "dvfs_group": row.dvfs_group,
        }
    return block


def merge_sim_block_into_catalog_yaml(text: str, sim_block: dict[str, Any]) -> str:
    """Merge a capabilities.sim block into an ip-*.yaml document."""

    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("catalog YAML root must be an object")
    capabilities = data.setdefault("capabilities", {})
    if not isinstance(capabilities, dict):
        raise ValueError("catalog YAML capabilities must be an object")
    capabilities["sim"] = sim_block
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)


def dump_yaml_fragment(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)


def _project_name(row: list[str]) -> str | None:
    if len(row) >= 2 and row[0].strip().lower() == "project":
        return row[1].strip() or None
    return None


def _find_header_index(rows: list[list[str]]) -> int | None:
    for idx, row in enumerate(rows):
        normalized = {_normalize_header(cell) for cell in row}
        if {"name", "mode", "unit_power", "ppc"}.issubset(normalized):
            return idx
    return None


def _normalize_header(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _cell(row: list[str], index: int) -> str:
    return row[index].strip() if index < len(row) else ""


def _optional_cell(row: list[str], index: int) -> str | None:
    value = _cell(row, index)
    return value or None


def _float_cell(row: list[str], index: int) -> float:
    value = _cell(row, index)
    return float(value) if value else 0.0
