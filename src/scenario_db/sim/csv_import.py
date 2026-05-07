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


@dataclass(frozen=True)
class SimImportResult:
    catalog_path: Path
    changed: bool
    hw_name: str | None
    role_count: int = 0


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


def build_sim_block_from_mapping_entry(
    rows: list[LegacySimModeRow],
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Build a capabilities.sim block from one mapping.yaml catalog entry."""

    hw_name = entry.get("hw_name")
    if hw_name:
        try:
            block = build_sim_block(rows, str(hw_name))
        except ValueError:
            if "base" not in entry:
                raise
            block = _explicit_base_block(entry)
    else:
        block = _explicit_base_block(entry)

    if entry.get("source_note"):
        block["source_note"] = str(entry["source_note"])

    role_modes = entry.get("role_modes") or {}
    if role_modes:
        if not isinstance(role_modes, dict):
            raise ValueError("role_modes must be a mapping of role -> legacy HW name")
        block["role_modes"] = {
            str(role): _role_sim_block(rows, role_entry)
            for role, role_entry in role_modes.items()
        }
    return block


def apply_sim_import_mapping(
    mapping_path: str | Path,
    *,
    csv_path: str | Path | None = None,
    catalog_root: str | Path | None = None,
    dry_run: bool = False,
) -> list[SimImportResult]:
    """Apply mapping.yaml to one or more catalog YAML files."""

    mapping_file = Path(mapping_path)
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict):
        raise ValueError("mapping YAML root must be an object")

    resolved_csv = _resolve_path(
        csv_path or mapping.get("source_csv"),
        base_dir=mapping_file.parent,
        field="source_csv",
    )
    resolved_root = _resolve_path(
        catalog_root or mapping.get("catalog_root") or ".",
        base_dir=mapping_file.parent,
        field="catalog_root",
    )
    rows = load_legacy_sim_info_csv(resolved_csv)

    catalog_entries = mapping.get("catalogs")
    if not isinstance(catalog_entries, list):
        raise ValueError("mapping YAML must contain a catalogs list")

    results: list[SimImportResult] = []
    for entry in catalog_entries:
        if not isinstance(entry, dict):
            raise ValueError("each catalogs item must be an object")
        catalog_value = entry.get("catalog") or entry.get("path")
        if not catalog_value:
            raise ValueError("each catalogs item must define catalog or path")
        catalog_path = Path(str(catalog_value))
        if not catalog_path.is_absolute():
            catalog_path = resolved_root / catalog_path
        if not catalog_path.exists():
            raise ValueError(f"catalog YAML not found: {catalog_path}")

        sim_block = build_sim_block_from_mapping_entry(rows, entry)
        original = catalog_path.read_text(encoding="utf-8")
        rendered = merge_sim_block_into_catalog_yaml(original, sim_block)
        changed = rendered != original
        if changed and not dry_run:
            catalog_path.write_text(rendered, encoding="utf-8")
        results.append(
            SimImportResult(
                catalog_path=catalog_path,
                changed=changed,
                hw_name=sim_block.get("hw_name"),
                role_count=len(sim_block.get("role_modes") or {}),
            )
        )
    return results


def merge_sim_block_into_catalog_yaml(text: str, sim_block: dict[str, Any]) -> str:
    """Merge a capabilities.sim block into an ip-*.yaml document."""

    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("catalog YAML root must be an object")
    capabilities = data.setdefault("capabilities", {})
    if not isinstance(capabilities, dict):
        raise ValueError("catalog YAML capabilities must be an object")
    if capabilities.get("sim") == sim_block:
        return text
    capabilities["sim"] = sim_block
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)


def dump_yaml_fragment(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)


def _explicit_base_block(entry: dict[str, Any]) -> dict[str, Any]:
    base = entry.get("base")
    if not isinstance(base, dict):
        raise ValueError("mapping entry without a valid CSV hw_name must define base")
    hw_name = base.get("hw_name") or entry.get("hw_name")
    if not hw_name:
        raise ValueError("base must define hw_name")
    modes = base.get("modes")
    if not isinstance(modes, dict):
        raise ValueError("base must define modes")
    block: dict[str, Any] = {
        "hw_name": str(hw_name),
        "source": "legacy_project_info_csv",
        "modes": modes,
    }
    if base.get("source_project"):
        block["source_project"] = str(base["source_project"])
    return block


def _role_sim_block(rows: list[LegacySimModeRow], role_entry: Any) -> dict[str, Any]:
    if isinstance(role_entry, str):
        block = build_sim_block(rows, role_entry)
    elif isinstance(role_entry, dict):
        if role_entry.get("hw_name"):
            block = build_sim_block(rows, str(role_entry["hw_name"]))
        elif role_entry.get("base"):
            block = _explicit_base_block(role_entry)
        else:
            raise ValueError("role mapping object must define hw_name or base")
    else:
        raise ValueError("role mapping must be a legacy HW name string or object")
    return {
        "hw_name": block["hw_name"],
        "modes": block["modes"],
    }


def _resolve_path(value: Any, *, base_dir: Path, field: str) -> Path:
    if value in (None, ""):
        raise ValueError(f"mapping YAML must define {field}")
    path = Path(str(value))
    if not path.is_absolute():
        path = base_dir / path
    return path


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
