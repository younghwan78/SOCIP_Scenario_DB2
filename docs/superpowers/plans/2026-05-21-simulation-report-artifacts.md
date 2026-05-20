# Simulation Report Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate legacy-style `timing_chart.html`, `bw_chart.html`, and `simulation_result.html` from stored `evidence.simulation`, integrate them into the current ScenarioDB Evidence Dashboard, and save the HTML bundle locally.

**Architecture:** Treat `evidence.simulation` as the single source of truth. Add a pure reporting layer under `src/scenario_db/reporting/` that builds chart/report HTML from an evidence dict plus optional DB-derived context, then expose it through a simulation artifact export API and Streamlit dashboard actions. Keep report generation independent of Streamlit so API, CLI, tests, and UI all use the same code path.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Pydantic, Plotly HTML export, Streamlit, pytest, PostgreSQL-backed `evidence.simulation`.

---

## Scope

This plan implements approach 1: `Simulation Evidence -> Report Projection -> HTML Artifacts`.

Included:

- Generate three local HTML artifacts:
  - `{prefix}_timing_chart.html`
  - `{prefix}_bw_chart.html`
  - `{prefix}_simulation_result.html`
- Use stored simulation evidence fields:
  - `kpi`
  - `execution_context`
  - `run_info`
  - `external_devices`
  - `dvfs_breakdown`
  - `dma_breakdown`
  - `timing_breakdown`
  - `timeline_events`
  - `topology_order`
  - `vdd_power`
  - `calculation_trace`
- Add Evidence Dashboard actions for saved evidence:
  - download report HTML directly from browser memory
  - request API-side local bundle export
  - show exported artifact paths and hashes
- Persist exported artifact metadata in `Evidence.artifacts`.

Excluded:

- Re-running the old legacy simulator.
- Reintroducing legacy `SimulationResults`, `ScenarioGraph`, or `ResolvedIPConfig` as runtime dependencies.
- Arbitrary browser-selected filesystem write paths.
- PNG/PDF chart export.
- Publishing to GitHub Pages.

## File Structure

Create:

- `src/scenario_db/reporting/__init__.py`  
  Public reporting package exports.
- `src/scenario_db/reporting/models.py`  
  Small dataclasses/Pydantic models for report context, generated HTML, and written artifacts.
- `src/scenario_db/reporting/filenames.py`  
  Safe artifact prefix and filename helpers.
- `src/scenario_db/reporting/tables.py`  
  Pure table row builders for report sections.
- `src/scenario_db/reporting/charts.py`  
  Plotly figure builders and HTML serializers for timing and BW charts.
- `src/scenario_db/reporting/html_report.py`  
  Legacy-style simulation report HTML generator.
- `src/scenario_db/reporting/exporter.py`  
  Local bundle writer and sha256/artifact metadata builder.
- `dashboard/components/simulation_report_actions.py`  
  Streamlit UI actions for HTML download and API-side export.
- `tests/unit/reporting/test_filenames.py`
- `tests/unit/reporting/test_tables.py`
- `tests/unit/reporting/test_charts.py`
- `tests/unit/reporting/test_html_report.py`
- `tests/unit/reporting/test_exporter.py`
- `tests/unit/dashboard/test_simulation_report_actions.py`

Modify:

- `pyproject.toml`  
  Move or duplicate `plotly>=5.20` into base dependencies because API-side report export needs Plotly outside Streamlit.
- `src/scenario_db/config.py`  
  Add `report_dir` setting backed by `SCENARIO_DB_REPORT_DIR`, defaulting to `output_simulation`.
- `src/scenario_db/api/schemas/simulation.py`  
  Add artifact export request/response schemas.
- `src/scenario_db/api/routers/simulation.py`  
  Add `POST /simulation/results/{evidence_id}/artifacts/export`.
- `src/scenario_db/db/repositories/evidence.py`  
  Add artifact metadata update helper.
- `dashboard/components/evidence_dashboard_contract.py`  
  Add button labels and report tab label.
- `dashboard/components/evidence_result_view.py`  
  Add `Report` tab or report action placement.
- `dashboard/components/evidence_actions.py`  
  Add saved-evidence export action wiring.
- `dashboard/components/simulation_api_client.py`  
  Add API client function for artifact export.
- `README.md` and `docs/dashboard-regression-checklist.md`  
  Document local HTML report export and verification.

---

### Task 1: Reporting Contract, Filenames, And Config

**Files:**

- Create: `src/scenario_db/reporting/__init__.py`
- Create: `src/scenario_db/reporting/models.py`
- Create: `src/scenario_db/reporting/filenames.py`
- Modify: `src/scenario_db/config.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/reporting/test_filenames.py`

- [ ] **Step 1: Write failing filename and config tests**

Create `tests/unit/reporting/test_filenames.py`:

```python
from __future__ import annotations

from pathlib import Path

from scenario_db.config import Settings
from scenario_db.reporting.filenames import (
    artifact_filenames,
    build_report_prefix,
    safe_report_slug,
)
from scenario_db.reporting.models import ReportContext


def test_safe_report_slug_preserves_legacy_readable_names():
    assert safe_report_slug("projectA-FHD30_Recording") == "projectA-FHD30_Recording"
    assert safe_report_slug("uc-camera-recording/UHD60 HDR10 H.265") == "uc-camera-recording-UHD60_HDR10_H.265"


def test_report_prefix_prefers_project_and_variant_when_available():
    context = ReportContext(
        evidence_id="sim-1",
        scenario_ref="uc-camera-recording",
        variant_ref="FHD30-SDR-H265",
        project_ref="projectA",
        scenario_name="Camera Recording",
        variant_name="FHD30 Recording",
    )

    assert build_report_prefix(context) == "projectA-FHD30_Recording"


def test_report_prefix_falls_back_to_scenario_and_variant():
    context = ReportContext(
        evidence_id="sim-1",
        scenario_ref="uc-camera-recording",
        variant_ref="cam-rec-f1-fhd30",
        project_ref=None,
        scenario_name=None,
        variant_name=None,
    )

    assert build_report_prefix(context) == "uc-camera-recording-cam-rec-f1-fhd30"


def test_artifact_filenames_match_legacy_suffixes():
    names = artifact_filenames("projectA-FHD30_Recording")

    assert names.timing_chart == "projectA-FHD30_Recording_timing_chart.html"
    assert names.bw_chart == "projectA-FHD30_Recording_bw_chart.html"
    assert names.simulation_report == "projectA-FHD30_Recording_simulation_result.html"


def test_report_dir_setting_defaults_to_output_simulation():
    settings = Settings()

    assert Path(settings.report_dir).as_posix().endswith("output_simulation")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
uv run --group dev pytest tests\unit\reporting\test_filenames.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scenario_db.reporting'`.

- [ ] **Step 3: Add reporting models and filename helpers**

Create `src/scenario_db/reporting/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ArtifactKind = Literal["timing_chart", "bw_chart", "simulation_report"]


@dataclass(frozen=True, slots=True)
class ReportContext:
    evidence_id: str
    scenario_ref: str
    variant_ref: str
    project_ref: str | None = None
    scenario_name: str | None = None
    variant_name: str | None = None
    soc_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactFilenames:
    timing_chart: str
    bw_chart: str
    simulation_report: str


@dataclass(frozen=True, slots=True)
class GeneratedReportBundle:
    prefix: str
    timing_chart_html: str | None
    bw_chart_html: str | None
    simulation_report_html: str


@dataclass(frozen=True, slots=True)
class WrittenArtifact:
    type: ArtifactKind
    storage: str
    path: Path
    sha256: str
    bytes: int
```

Create `src/scenario_db/reporting/filenames.py`:

```python
from __future__ import annotations

import re

from scenario_db.reporting.models import ArtifactFilenames, ReportContext


_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")
_DASH_RUN = re.compile(r"-+")


def safe_report_slug(value: str) -> str:
    text = str(value or "").strip().replace(" ", "_")
    text = _UNSAFE_CHARS.sub("-", text)
    text = _DASH_RUN.sub("-", text).strip("-._")
    return text[:140] or "simulation-report"


def build_report_prefix(context: ReportContext) -> str:
    project = context.project_ref or context.soc_ref or context.scenario_ref
    variant = context.variant_name or context.variant_ref
    return safe_report_slug(f"{project}-{variant}")


def artifact_filenames(prefix: str) -> ArtifactFilenames:
    safe_prefix = safe_report_slug(prefix)
    return ArtifactFilenames(
        timing_chart=f"{safe_prefix}_timing_chart.html",
        bw_chart=f"{safe_prefix}_bw_chart.html",
        simulation_report=f"{safe_prefix}_simulation_result.html",
    )
```

Create `src/scenario_db/reporting/__init__.py`:

```python
from scenario_db.reporting.filenames import artifact_filenames, build_report_prefix, safe_report_slug
from scenario_db.reporting.models import ArtifactFilenames, GeneratedReportBundle, ReportContext, WrittenArtifact

__all__ = [
    "ArtifactFilenames",
    "GeneratedReportBundle",
    "ReportContext",
    "WrittenArtifact",
    "artifact_filenames",
    "build_report_prefix",
    "safe_report_slug",
]
```

- [ ] **Step 4: Add report directory setting**

Modify `src/scenario_db/config.py`:

```python
class Settings(BaseSettings):
    database_url: str = Field(
        default="sqlite:///:memory:",
        validation_alias=AliasChoices("SCENARIO_DB_DATABASE_URL", "DATABASE_URL"),
    )
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:8501", "http://localhost:3000"]
    log_level: str = "INFO"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    report_dir: str = "output_simulation"
```

Keep the existing `model_config` unchanged so `SCENARIO_DB_REPORT_DIR` works through the existing env prefix.

- [ ] **Step 5: Add Plotly to API/base dependencies**

Modify `pyproject.toml` project dependencies:

```toml
dependencies = [
    "alembic>=1.18.4",
    "fastapi>=0.115",
    "plotly>=5.20",
    "psycopg2-binary>=2.9.11",
    "pydantic>=2.13.2",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0.3",
    "sqlalchemy>=2.0.49",
    "uvicorn[standard]>=0.30",
]
```

Leave the existing dashboard group unchanged for the first pass. `uv` will resolve the duplicate constraint consistently.

- [ ] **Step 6: Run tests**

Run:

```powershell
uv run --group dev pytest tests\unit\reporting\test_filenames.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add pyproject.toml src\scenario_db\config.py src\scenario_db\reporting tests\unit\reporting\test_filenames.py
git commit -m "feat: add simulation report artifact contract"
```

---

### Task 2: Report Table Projection From Evidence

**Files:**

- Create: `src/scenario_db/reporting/tables.py`
- Test: `tests/unit/reporting/test_tables.py`

- [ ] **Step 1: Write failing table projection tests**

Create `tests/unit/reporting/test_tables.py`:

```python
from __future__ import annotations

from scenario_db.reporting.tables import (
    basic_conditions_rows,
    dma_report_rows,
    dvfs_guide_rows,
    ip_detail_rows,
    power_summary_rows,
    scenario_description_rows,
)


def _evidence() -> dict:
    return {
        "id": "sim-1",
        "scenario_ref": "uc-camera-recording",
        "variant_ref": "FHD30-SDR-H265",
        "execution_context": {
            "silicon_rev": "EVT0",
            "sw_baseline_ref": "sw-vendor-v1.2.3",
            "thermal": "normal",
            "ambient_temp_c": 25.0,
        },
        "run_info": {"timestamp": "2026-05-21T01:02:03+09:00", "tool": "scenariodb-sim"},
        "kpi": {
            "total_power_mw": 120.0,
            "total_power_ma": 35.294,
            "core_power_mw": 100.0,
            "bw_power_mw": 20.0,
            "total_bw_mbs": 2500.0,
            "hw_time_max_ms": 12.5,
            "timeline_end_ms": 33.3,
        },
        "external_devices": [
            {"device_type": "sensor", "node_id": "sensor", "name": "HP2", "active_size": "1920x1080", "fps": 30, "format": "RAW10", "v_valid_ms": 18.2}
        ],
        "dvfs_breakdown": [
            {
                "node_id": "isp",
                "ip_ref": "ip-isp",
                "hw_name": "ISP",
                "mode": "Normal",
                "dvfs_group": "CAM",
                "required_clock_mhz": 300.0,
                "set_clock_mhz": 332.0,
                "dvfs_level": 4,
                "required_voltage_mv": 600.0,
                "set_voltage_mv": 606.25,
                "vdd": "VDD_CAM",
                "ppc": 4,
                "unit_power_mw_mp": 9.92,
                "input_resolution_mp": 2.0736,
                "fps": 30.0,
                "total_power_mw": 100.0,
                "total_power_ma": 29.412,
            }
        ],
        "dma_breakdown": [
            {
                "node_id": "isp",
                "hw_name": "ISP",
                "port": "ISP_WDMA",
                "direction": "write",
                "width": 1920,
                "height": 1080,
                "format": "NV12",
                "bitwidth": 8,
                "compression": "disable",
                "bw_mbs": 93.312,
                "bw_power_mw": 7.465,
                "bw_power_ma": 2.195,
            }
        ],
        "vdd_power": {"VDD_CAM": {"core_mw": 100.0, "bw_mw": 7.465, "total_mw": 107.465}},
    }


def test_scenario_description_uses_external_sensor_and_kpi():
    rows = scenario_description_rows(_evidence())

    assert rows["Scenario"] == "uc-camera-recording"
    assert rows["Variant"] == "FHD30-SDR-H265"
    assert rows["Sensor"] == "HP2"
    assert rows["Resolution"] == "1920x1080"
    assert rows["FPS"] == "30"


def test_basic_conditions_include_execution_context_and_run_info():
    rows = basic_conditions_rows(_evidence())

    assert rows["Silicon Rev"] == "EVT0"
    assert rows["SW Baseline"] == "sw-vendor-v1.2.3"
    assert rows["Thermal"] == "normal"
    assert rows["Ambient"] == "25 C"
    assert rows["Tool"] == "scenariodb-sim"


def test_dvfs_power_ip_and_dma_rows_have_legacy_units():
    evidence = _evidence()

    assert dvfs_guide_rows(evidence)[0]["DVFS Domain"] == "CAM"
    assert power_summary_rows(evidence)[0]["VDD"] == "VDD_CAM"
    assert ip_detail_rows(evidence)[0]["HW Time(ms)"] == "12.500"
    assert dma_report_rows(evidence)[0]["BW (MB/s)"] == "93.3"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
uv run --group dev pytest tests\unit\reporting\test_tables.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scenario_db.reporting.tables'`.

- [ ] **Step 3: Implement table builders**

Create `src/scenario_db/reporting/tables.py`:

```python
from __future__ import annotations

from typing import Any


def scenario_description_rows(evidence: dict[str, Any]) -> dict[str, str]:
    sensor = _first_external(evidence, "sensor")
    kpi = _dict(evidence.get("kpi"))
    return {
        "Scenario": _text(evidence.get("scenario_ref")),
        "Variant": _text(evidence.get("variant_ref")),
        "Sensor": _text(sensor.get("name") or sensor.get("ip_ref") or sensor.get("node_id")),
        "Resolution": _size_text(sensor),
        "FPS": _number_text(sensor.get("fps") or kpi.get("fps")),
        "Format": _text(sensor.get("format")),
        "Timeline End": _ms(kpi.get("timeline_end_ms")),
    }


def basic_conditions_rows(evidence: dict[str, Any]) -> dict[str, str]:
    context = _dict(evidence.get("execution_context"))
    run_info = _dict(evidence.get("run_info"))
    ambient = _number(context.get("ambient_temp_c"))
    return {
        "Silicon Rev": _text(context.get("silicon_rev")),
        "SW Baseline": _text(evidence.get("sw_baseline_ref") or context.get("sw_baseline_ref")),
        "Thermal": _text(context.get("thermal")),
        "Ambient": "-" if ambient is None else f"{ambient:g} C",
        "Tool": _text(run_info.get("tool")),
        "Timestamp": _text(run_info.get("timestamp")),
        "Params Hash": _text(evidence.get("params_hash")),
    }


def dvfs_guide_rows(evidence: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    seen: set[str] = set()
    for item in _list(evidence.get("dvfs_breakdown")):
        group = _text(item.get("dvfs_group"))
        if not group or group == "-" or group in seen:
            continue
        seen.add(group)
        rows.append(
            {
                "DVFS Domain": group,
                "Set Clock (MHz)": _fixed(item.get("set_clock_mhz"), 1),
                "DVFS Level": _text(item.get("dvfs_level")),
                "Set Voltage (mV)": _fixed(item.get("set_voltage_mv"), 2),
            }
        )
    if evidence.get("kpi", {}).get("total_bw_mbs") is not None:
        rows.append(
            {
                "DVFS Domain": "MIF",
                "Set Clock (MHz)": "-",
                "DVFS Level": "derived from total BW",
                "Set Voltage (mV)": "-",
            }
        )
    return rows


def power_summary_rows(evidence: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    vdd_power = _dict(evidence.get("vdd_power"))
    for vdd, values in sorted(vdd_power.items()):
        value_map = _dict(values)
        rows.append(
            {
                "VDD": str(vdd),
                "Core Power (mW)": _fixed(value_map.get("core_mw"), 2),
                "BW Power (mW)": _fixed(value_map.get("bw_mw"), 2),
                "Total Power (mW)": _fixed(value_map.get("total_mw"), 2),
            }
        )
    kpi = _dict(evidence.get("kpi"))
    rows.append(
        {
            "VDD": "Total",
            "Core Power (mW)": _fixed(kpi.get("core_power_mw"), 2),
            "BW Power (mW)": _fixed(kpi.get("bw_power_mw"), 2),
            "Total Power (mW)": _fixed(kpi.get("total_power_mw"), 2),
            "Total Current (mA)": _fixed(kpi.get("total_power_ma"), 2),
        }
    )
    return rows


def ip_detail_rows(evidence: dict[str, Any]) -> list[dict[str, str]]:
    timing_by_node = {str(item.get("node_id")): item for item in _list(evidence.get("timing_breakdown"))}
    kpi = _dict(evidence.get("kpi"))
    rows = []
    for item in _list(evidence.get("dvfs_breakdown")):
        timing = timing_by_node.get(str(item.get("node_id"))) or {}
        rows.append(
            {
                "Node": _text(item.get("node_id")),
                "IP Ref": _text(item.get("ip_ref")),
                "HW": _text(item.get("hw_name")),
                "Mode": _text(item.get("mode")),
                "PPC": _number_text(item.get("ppc")),
                "Unit Power": _fixed(item.get("unit_power_mw_mp"), 3),
                "Input Res": _resolution_text(item),
                "VDD": _text(item.get("vdd")),
                "DVFS": _text(item.get("dvfs_group")),
                "Req Freq": _fixed(item.get("required_clock_mhz"), 1),
                "Set Freq": _fixed(item.get("set_clock_mhz"), 1),
                "Set Volt": _fixed(item.get("set_voltage_mv"), 2),
                "Power(mW)": _fixed(item.get("total_power_mw"), 2),
                "Current(mA)": _fixed(item.get("total_power_ma"), 2),
                "HW Time(ms)": _fixed(timing.get("hw_time_ms") or kpi.get("hw_time_max_ms"), 3),
            }
        )
    return rows


def dma_report_rows(evidence: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for item in _list(evidence.get("dma_breakdown")):
        rows.append(
            {
                "Node": _text(item.get("node_id")),
                "HW": _text(item.get("hw_name")),
                "Name": _text(item.get("port")),
                "In/Out": _text(item.get("direction")).title(),
                "WxH": _wh(item),
                "Format": _text(item.get("format")),
                "Bitwidth": _text(item.get("bitwidth")),
                "Comp": _text(item.get("compression")),
                "BW (MB/s)": _fixed(item.get("bw_mbs"), 1),
                "BW Power (mW)": _fixed(item.get("bw_power_mw"), 2),
                "BW Current (mA)": _fixed(item.get("bw_power_ma"), 2),
                "LLC": _text(item.get("llc_enabled")),
            }
        )
    return rows


def _first_external(evidence: dict[str, Any], device_type: str) -> dict[str, Any]:
    for item in _list(evidence.get("external_devices")):
        if str(item.get("device_type") or "").lower() == device_type:
            return item
    return {}


def _size_text(row: dict[str, Any]) -> str:
    value = row.get("active_size") or row.get("catalog_size") or row.get("size")
    if isinstance(value, str) and value:
        return value
    return _wh(row)


def _resolution_text(row: dict[str, Any]) -> str:
    width = _number(row.get("width"))
    height = _number(row.get("height"))
    if width and height:
        return f"{int(width)}x{int(height)}"
    mp = _number(row.get("input_resolution_mp"))
    return "-" if mp is None else f"{mp:.3f} MP"


def _wh(row: dict[str, Any]) -> str:
    width = _number(row.get("width"))
    height = _number(row.get("height"))
    return "-" if not width or not height else f"{int(width)}x{int(height)}"


def _ms(value: Any) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:.3f} ms"


def _fixed(value: Any, digits: int) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:.{digits}f}"


def _number_text(value: Any) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:g}"


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return "-" if value is None or value == "" else str(value)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]
```

- [ ] **Step 4: Run tests**

Run:

```powershell
uv run --group dev pytest tests\unit\reporting\test_tables.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src\scenario_db\reporting\tables.py tests\unit\reporting\test_tables.py
git commit -m "feat: project simulation evidence into report tables"
```

---

### Task 3: Timing And BW HTML Chart Generators

**Files:**

- Create: `src/scenario_db/reporting/charts.py`
- Test: `tests/unit/reporting/test_charts.py`

- [ ] **Step 1: Write failing chart tests**

Create `tests/unit/reporting/test_charts.py`:

```python
from __future__ import annotations

from scenario_db.reporting.charts import (
    bw_chart_records,
    generate_bw_chart_html,
    generate_timing_chart_html,
    timing_chart_records,
)


def _evidence() -> dict:
    return {
        "id": "sim-1",
        "scenario_ref": "uc-camera-recording",
        "variant_ref": "FHD30-SDR-H265",
        "topology_order": ["sensor", "csis", "isp", "mfc"],
        "timeline_events": [
            {"task_id": "sensor#f0", "node_id": "sensor", "hw_name": "HP2", "constraint_type": "source", "frame_index": 0, "start_ms": 0.0, "end_ms": 18.0, "duration_ms": 18.0},
            {"task_id": "csis#f0", "node_id": "csis", "hw_name": "CSIS", "edge_type": "OTF", "otf_group_id": "otf0#f0", "frame_index": 0, "start_ms": 0.0, "end_ms": 18.0, "duration_ms": 18.0},
            {"task_id": "isp#f0", "node_id": "isp", "hw_name": "ISP", "edge_type": "M2M", "frame_index": 0, "start_ms": 18.0, "end_ms": 24.0, "duration_ms": 6.0},
            {"task_id": "mfc#f0", "node_id": "mfc", "hw_name": "MFC", "edge_type": "M2M", "frame_index": 0, "start_ms": 24.0, "end_ms": 30.0, "duration_ms": 6.0},
        ],
        "dma_breakdown": [
            {"node_id": "isp", "hw_name": "ISP", "port": "ISP_WDMA", "direction": "write", "bw_mbs": 1000.0, "bw_power_mw": 80.0, "bw_power_ma": 23.5},
            {"node_id": "mfc", "hw_name": "MFC", "port": "MFC_RDMA", "direction": "read", "bw_mbs": 500.0, "bw_power_mw": 40.0, "bw_power_ma": 11.8},
        ],
    }


def test_timing_chart_records_group_events_by_timeline_fields():
    records = timing_chart_records(_evidence())

    assert records[0]["label"].startswith("F0 /")
    assert any(row["otf_group_id"] == "otf0" for row in records)
    assert any(row["edge_type"] == "M2M" for row in records)


def test_bw_chart_records_join_dma_to_timeline_by_node():
    records = bw_chart_records(_evidence())

    assert [row["node_id"] for row in records] == ["isp", "mfc"]
    assert records[0]["start_ms"] == 18.0
    assert records[0]["end_ms"] == 24.0
    assert records[0]["bw_gbps"] == 1.0
    assert records[1]["direction"] == "Read"


def test_chart_html_contains_plotly_and_legacy_titles():
    timing_html = generate_timing_chart_html(_evidence(), title="FHD30_Recording")
    bw_html = generate_bw_chart_html(_evidence(), title="FHD30_Recording - Bandwidth Timeline")

    assert "Plotly.newPlot" in timing_html
    assert "FHD30_Recording" in timing_html
    assert "Plotly.newPlot" in bw_html
    assert "Total BW" in bw_html
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
uv run --group dev pytest tests\unit\reporting\test_charts.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scenario_db.reporting.charts'`.

- [ ] **Step 3: Implement chart record builders and Plotly serializers**

Create `src/scenario_db/reporting/charts.py`:

```python
from __future__ import annotations

from collections import defaultdict
from typing import Any


def timing_chart_records(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for event in _events(evidence):
        frame = event.get("frame_index")
        otf_group = _base_group(event.get("otf_group_id"))
        label = _timing_label(event, include_frame=frame is not None)
        rows.append(
            {
                "task_id": str(event.get("task_id") or ""),
                "node_id": str(event.get("node_id") or ""),
                "hw_name": str(event.get("hw_name") or event.get("node_id") or "task"),
                "label": label,
                "frame_index": frame,
                "start_ms": _float(event.get("start_ms")),
                "end_ms": _float(event.get("end_ms")),
                "duration_ms": _duration(event),
                "task_type": str(event.get("task_type") or ""),
                "constraint_type": event.get("constraint_type"),
                "edge_type": str(event.get("edge_type") or ""),
                "otf_group_id": otf_group,
                "critical": bool(event.get("critical")),
                "hover": _timing_hover(event),
            }
        )
    return sorted(rows, key=lambda row: (row["frame_index"] or 0, row["start_ms"], row["end_ms"], row["label"]))


def bw_chart_records(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    event_by_node = _timeline_window_by_node(evidence)
    rows = []
    for item in _dict_rows(evidence.get("dma_breakdown")):
        node_id = str(item.get("node_id") or "")
        window = event_by_node.get(node_id)
        if window is None:
            continue
        direction = str(item.get("direction") or "").lower()
        rows.append(
            {
                "node_id": node_id,
                "hw_name": str(item.get("hw_name") or node_id),
                "port": str(item.get("port") or ""),
                "direction": "Read" if direction == "read" else "Write" if direction == "write" else "OTF",
                "start_ms": window["start_ms"],
                "end_ms": window["end_ms"],
                "duration_ms": max(0.0, window["end_ms"] - window["start_ms"]),
                "frame_index": window.get("frame_index"),
                "bw_mbs": _float(item.get("bw_mbs")),
                "bw_gbps": _float(item.get("bw_mbs")) / 1000.0,
                "bw_power_mw": _float(item.get("bw_power_mw")),
                "bw_power_ma": _float(item.get("bw_power_ma")),
            }
        )
    rank = {str(node): index for index, node in enumerate(evidence.get("topology_order") or [])}
    return sorted(rows, key=lambda row: (row["frame_index"] or 0, rank.get(row["node_id"], 10_000), row["start_ms"], row["port"]))


def generate_timing_chart_html(evidence: dict[str, Any], *, title: str) -> str:
    import plotly.graph_objects as go

    records = timing_chart_records(evidence)
    fig = go.Figure()
    colors = _timing_colors()
    for row in records:
        color = _timing_color(row, colors)
        fig.add_trace(
            go.Bar(
                x=[row["duration_ms"]],
                y=[row["label"]],
                base=[row["start_ms"]],
                orientation="h",
                name=_timing_legend(row),
                marker={
                    "color": color,
                    "line": {"color": "#B91C1C" if row["critical"] else color, "width": 2 if row["critical"] else 0},
                },
                hovertemplate=row["hover"] + "<extra></extra>",
                text=row["task_id"].split("#f", 1)[0],
                textposition="inside",
                showlegend=True,
            )
        )
    fig.update_layout(
        title=title,
        xaxis_title="Time (ms)",
        yaxis_title="Hardware",
        barmode="overlay",
        height=max(420, min(1100, 300 + len({row["label"] for row in records}) * 40)),
        margin={"t": 60, "r": 160, "b": 40, "l": 120},
    )
    fig.update_yaxes(autorange="reversed")
    return fig.to_html(full_html=True, include_plotlyjs="cdn")


def generate_bw_chart_html(evidence: dict[str, Any], *, title: str) -> str:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    records = bw_chart_records(evidence)
    if not records:
        return _empty_html(title, "No DMA timeline records are available. Run simulation with timeline enabled.")

    ips = []
    for row in records:
        if row["hw_name"] not in ips:
            ips.append(row["hw_name"])
    total_power_mw = sum(row["bw_power_mw"] for row in records)
    total_power_ma = sum(row["bw_power_ma"] for row in records)
    total_bw_gbps = sum(row["bw_gbps"] for row in records)
    subplot_titles = [f"Total BW (Avg: {total_bw_gbps:.2f} GB/s, Power: {total_power_mw:.1f} mW / {total_power_ma:.1f} mA)"]
    for ip in ips:
        ip_rows = [row for row in records if row["hw_name"] == ip]
        subplot_titles.append(
            f"{ip} BW ({sum(row['bw_gbps'] for row in ip_rows):.2f} GB/s, "
            f"{sum(row['bw_power_mw'] for row in ip_rows):.1f} mW / {sum(row['bw_power_ma'] for row in ip_rows):.1f} mA)"
        )

    fig = make_subplots(rows=1 + len(ips), cols=1, shared_xaxes=True, vertical_spacing=0.03, subplot_titles=subplot_titles)
    palette = _bw_palettes()
    _add_bw_traces(fig, records, row=1, show_legend=True, palette=palette)
    for index, ip in enumerate(ips, start=2):
        _add_bw_traces(fig, [row for row in records if row["hw_name"] == ip], row=index, show_legend=False, palette=palette)

    y_max = max(1.0, sum(row["bw_gbps"] for row in records)) * 1.1
    for row_index in range(1, 2 + len(ips)):
        fig.update_yaxes(title_text="GB/s", range=[0, y_max], row=row_index, col=1)
    fig.update_xaxes(title_text="Time (ms)", row=1 + len(ips), col=1)
    fig.update_layout(
        title=title,
        barmode="stack",
        height=260 + (1 + len(ips)) * 360,
        showlegend=True,
        legend={"orientation": "v", "yanchor": "top", "y": 1.0, "xanchor": "left", "x": 1.02, "font": {"size": 9}},
        margin={"t": 70, "r": 220, "b": 40, "l": 70},
    )
    return fig.to_html(full_html=True, include_plotlyjs="cdn")


def _add_bw_traces(fig: Any, records: list[dict[str, Any]], *, row: int, show_legend: bool, palette: dict[str, list[str]]) -> None:
    import plotly.graph_objects as go

    for index, item in enumerate(records):
        direction = item["direction"]
        colors = palette["read"] if direction == "Read" else palette["write"]
        color = colors[index % len(colors)]
        fig.add_trace(
            go.Bar(
                x=[(item["start_ms"] + item["end_ms"]) / 2.0],
                y=[item["bw_gbps"]],
                width=[item["duration_ms"]],
                name=f"{item['port']} ({direction[:1]})",
                marker={"color": color, "line": {"color": color.replace("0.75", "1.0"), "width": 1}},
                showlegend=show_legend,
                hovertemplate=(
                    f"{item['hw_name']} / {item['port']}<br>"
                    f"Direction: {direction}<br>"
                    f"BW: {item['bw_gbps']:.2f} GB/s ({item['bw_mbs']:.1f} MB/s)<br>"
                    f"Start: {item['start_ms']:.3f} ms<br>"
                    f"End: {item['end_ms']:.3f} ms<br>"
                    f"Duration: {item['duration_ms']:.3f} ms<br>"
                    f"Power: {item['bw_power_mw']:.2f} mW / {item['bw_power_ma']:.2f} mA<br>"
                    f"Frame: {item['frame_index'] if item['frame_index'] is not None else '-'}"
                    "<extra></extra>"
                ),
            ),
            row=row,
            col=1,
        )


def _timeline_window_by_node(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for event in _events(evidence):
        node_id = str(event.get("node_id") or "")
        if not node_id:
            continue
        result.setdefault(
            node_id,
            {
                "start_ms": _float(event.get("start_ms")),
                "end_ms": _float(event.get("end_ms")),
                "frame_index": event.get("frame_index"),
            },
        )
    return result


def _events(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return _dict_rows(evidence.get("timeline_events"))


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _timing_label(event: dict[str, Any], *, include_frame: bool) -> str:
    name = str(event.get("hw_name") or event.get("node_id") or event.get("task_id") or "task")
    prefix = f"F{event.get('frame_index')} / " if include_frame else ""
    group = _base_group(event.get("otf_group_id"))
    return prefix + (group or name)


def _base_group(value: Any) -> str | None:
    if not value:
        return None
    return str(value).split("#f", 1)[0]


def _duration(event: dict[str, Any]) -> float:
    duration = _float(event.get("duration_ms"))
    if duration:
        return duration
    return max(0.0, _float(event.get("end_ms")) - _float(event.get("start_ms")))


def _timing_hover(event: dict[str, Any]) -> str:
    return "<br>".join(
        [
            f"task: {event.get('task_id') or '-'}",
            f"node: {event.get('node_id') or '-'}",
            f"hw: {event.get('hw_name') or '-'}",
            f"start: {_float(event.get('start_ms')):.3f} ms",
            f"end: {_float(event.get('end_ms')):.3f} ms",
            f"duration: {_duration(event):.3f} ms",
            f"edge: {event.get('edge_type') or '-'}",
        ]
    )


def _timing_legend(row: dict[str, Any]) -> str:
    if row["constraint_type"] == "source":
        return "Sensor In"
    if row["constraint_type"] == "sink":
        return "Display Out"
    if row["otf_group_id"]:
        return f"OTF {row['otf_group_id']}"
    if row["edge_type"].upper() == "M2M":
        return "M2M"
    if "sw" in row["task_type"].lower():
        return "SW"
    return "HW"


def _timing_color(row: dict[str, Any], colors: dict[str, str]) -> str:
    legend = _timing_legend(row)
    if legend.startswith("OTF"):
        return colors["otf"]
    return colors.get(legend.lower().replace(" ", "_"), colors["hw"])


def _timing_colors() -> dict[str, str]:
    return {
        "sensor_in": "#22C55E",
        "display_out": "#0EA5E9",
        "otf": "#2F6F68",
        "m2m": "#D97706",
        "sw": "#9333EA",
        "hw": "#64748B",
    }


def _bw_palettes() -> dict[str, list[str]]:
    return {
        "read": ["rgba(33, 113, 181, 0.75)", "rgba(35, 139, 69, 0.75)", "rgba(66, 146, 198, 0.75)", "rgba(49, 163, 84, 0.75)"],
        "write": ["rgba(228, 26, 28, 0.75)", "rgba(255, 191, 0, 0.75)", "rgba(227, 74, 51, 0.75)", "rgba(255, 127, 0, 0.75)"],
    }


def _empty_html(title: str, message: str) -> str:
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title></head><body><h1>{title}</h1><p>{message}</p></body></html>"


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
```

- [ ] **Step 4: Run chart tests**

Run:

```powershell
uv run --group dev pytest tests\unit\reporting\test_charts.py -v
```

Expected: PASS.

- [ ] **Step 5: Run existing dashboard timing chart tests**

Run:

```powershell
uv run --group dev --group dashboard pytest tests\unit\dashboard\test_timing_chart.py -v
```

Expected: PASS. This guards the current in-dashboard Timing Chart behavior while export chart logic is added separately.

- [ ] **Step 6: Commit**

```powershell
git add src\scenario_db\reporting\charts.py tests\unit\reporting\test_charts.py
git commit -m "feat: generate simulation timing and bandwidth html charts"
```

---

### Task 4: Legacy-Style Simulation Report HTML

**Files:**

- Create: `src/scenario_db/reporting/html_report.py`
- Test: `tests/unit/reporting/test_html_report.py`

- [ ] **Step 1: Write failing HTML report tests**

Create `tests/unit/reporting/test_html_report.py`:

```python
from __future__ import annotations

from scenario_db.reporting.html_report import generate_simulation_report_html
from scenario_db.reporting.models import ReportContext


def _evidence() -> dict:
    return {
        "id": "sim-1",
        "scenario_ref": "uc-camera-recording",
        "variant_ref": "FHD30-SDR-H265",
        "sw_baseline_ref": "sw-vendor-v1.2.3",
        "execution_context": {"silicon_rev": "EVT0", "thermal": "normal", "ambient_temp_c": 25},
        "run_info": {"timestamp": "2026-05-21T01:02:03+09:00", "tool": "scenariodb-sim"},
        "kpi": {"total_power_mw": 120.0, "total_power_ma": 35.294, "core_power_mw": 100.0, "bw_power_mw": 20.0, "total_bw_mbs": 2500.0, "hw_time_max_ms": 12.5},
        "external_devices": [{"device_type": "sensor", "name": "HP2", "active_size": "1920x1080", "fps": 30, "format": "RAW10"}],
        "dvfs_breakdown": [{"node_id": "isp", "hw_name": "ISP", "mode": "Normal", "dvfs_group": "CAM", "set_clock_mhz": 332, "dvfs_level": 4, "set_voltage_mv": 606.25, "vdd": "VDD_CAM", "ppc": 4, "unit_power_mw_mp": 9.92, "input_resolution_mp": 2.0736, "fps": 30, "total_power_mw": 100.0, "total_power_ma": 29.412}],
        "timing_breakdown": [{"node_id": "isp", "hw_name": "ISP", "hw_time_ms": 12.5}],
        "dma_breakdown": [{"node_id": "isp", "hw_name": "ISP", "port": "ISP_WDMA", "direction": "write", "width": 1920, "height": 1080, "format": "NV12", "bitwidth": 8, "compression": "disable", "bw_mbs": 93.312, "bw_power_mw": 7.465, "bw_power_ma": 2.195}],
        "vdd_power": {"VDD_CAM": {"core_mw": 100.0, "bw_mw": 7.465, "total_mw": 107.465}},
    }


def test_simulation_report_html_contains_legacy_sections_and_chart_links():
    html = generate_simulation_report_html(
        _evidence(),
        context=ReportContext(
            evidence_id="sim-1",
            scenario_ref="uc-camera-recording",
            variant_ref="FHD30-SDR-H265",
            project_ref="projectA",
            variant_name="FHD30 Recording",
        ),
        timing_chart_file="projectA-FHD30_Recording_timing_chart.html",
        bw_chart_file="projectA-FHD30_Recording_bw_chart.html",
    )

    assert "<title>FHD30 Recording" in html
    assert "1. Scenario Description" in html
    assert "2. Basic Conditions" in html
    assert "3. DVFS Guide" in html
    assert "4. Power Results" in html
    assert "5. Clock Results" in html
    assert "6. IP Details" in html
    assert "7. DMA Results" in html
    assert "projectA-FHD30_Recording_timing_chart.html" in html
    assert "projectA-FHD30_Recording_bw_chart.html" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
uv run --group dev pytest tests\unit\reporting\test_html_report.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scenario_db.reporting.html_report'`.

- [ ] **Step 3: Implement HTML report generator**

Create `src/scenario_db/reporting/html_report.py`:

```python
from __future__ import annotations

from html import escape
from typing import Any

from scenario_db.reporting.models import ReportContext
from scenario_db.reporting.tables import (
    basic_conditions_rows,
    dma_report_rows,
    dvfs_guide_rows,
    ip_detail_rows,
    power_summary_rows,
    scenario_description_rows,
)


def generate_simulation_report_html(
    evidence: dict[str, Any],
    *,
    context: ReportContext,
    timing_chart_file: str | None = None,
    bw_chart_file: str | None = None,
) -> str:
    title = context.variant_name or context.variant_ref or context.evidence_id
    html = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='UTF-8'>",
        f"<title>{escape(title)} - Simulation Report</title>",
        "<style>",
        _css(),
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{escape(title)} - Simulation Report<span class='timestamp'>{escape(_timestamp(evidence))}</span></h1>",
        _chart_links(timing_chart_file=timing_chart_file, bw_chart_file=bw_chart_file),
        "<div class='two-col'>",
        "<div class='col'>",
        "<h2>1. Scenario Description</h2>",
        _kv_table(scenario_description_rows(evidence), class_name="info"),
        "</div>",
        "<div class='col'>",
        "<h2>2. Basic Conditions</h2>",
        _kv_table(basic_conditions_rows(evidence), class_name="info"),
        "</div>",
        "</div>",
        "<h2>3. DVFS Guide</h2>",
        _rows_table(dvfs_guide_rows(evidence)),
        "<h2>4. Power Results</h2>",
        _rows_table(power_summary_rows(evidence), total_marker="Total"),
        "<h2>5. Clock Results</h2>",
        _rows_table(ip_detail_rows(evidence)),
        "<h2>6. IP Details</h2>",
        _rows_table(ip_detail_rows(evidence)),
        "<h2>7. DMA Results</h2>",
        _rows_table(dma_report_rows(evidence)),
        "</body>",
        "</html>",
    ]
    return "\n".join(part for part in html if part)


def _timestamp(evidence: dict[str, Any]) -> str:
    run_info = evidence.get("run_info") if isinstance(evidence.get("run_info"), dict) else {}
    return str(run_info.get("timestamp") or "")


def _chart_links(*, timing_chart_file: str | None, bw_chart_file: str | None) -> str:
    links = []
    if timing_chart_file:
        links.append(f"<a href='{escape(timing_chart_file)}'>Timing Chart</a>")
    if bw_chart_file:
        links.append(f"<a href='{escape(bw_chart_file)}'>BW Chart</a>")
    if not links:
        return ""
    return "<div class='chart-links'>Charts: " + " | ".join(links) + "</div>"


def _kv_table(rows: dict[str, str], *, class_name: str = "") -> str:
    body = "\n".join(f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>" for key, value in rows.items())
    cls = f" class='{class_name}'" if class_name else ""
    return f"<table{cls}><tbody>{body}</tbody></table>"


def _rows_table(rows: list[dict[str, str]], *, total_marker: str | None = None) -> str:
    if not rows:
        return "<p class='empty'>No data available.</p>"
    columns = list(rows[0])
    header = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
    body_rows = []
    for row in rows:
        cls = " class='total'" if total_marker and row.get(columns[0]) == total_marker else ""
        cells = "".join(f"<td>{escape(str(row.get(column, '-')))}</td>" for column in columns)
        body_rows.append(f"<tr{cls}>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _css() -> str:
    return """
body {
  font-family: 'Segoe UI', Arial, sans-serif;
  max-width: 1400px;
  margin: 32px auto;
  padding: 0 24px;
  background: #F7F4EF;
  color: #111827;
}
h1 {
  color: #174D47;
  font-size: 1.6em;
  font-weight: 700;
  border-bottom: 2px solid #DED8CF;
  padding-bottom: 10px;
}
h2 {
  color: #2F6F68;
  margin-top: 28px;
  font-size: 1.15em;
  border-left: 4px solid #B9D2CC;
  padding-left: 10px;
}
.two-col { display: flex; gap: 24px; flex-wrap: wrap; }
.two-col .col { flex: 1; min-width: 300px; }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0 20px;
  background: #FFFFFF;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(16,24,40,0.08);
  font-size: 0.85em;
  overflow: hidden;
}
th {
  background: #E8F1EF;
  color: #174D47;
  padding: 8px 10px;
  font-weight: 700;
  text-align: center;
  white-space: nowrap;
}
td {
  padding: 6px 10px;
  border-bottom: 1px solid #F1F3F4;
  text-align: center;
  white-space: nowrap;
}
table.info th { text-align: left; min-width: 140px; background: #F5EBDD; color: #7C2D12; }
table.info td { text-align: left; }
tr:nth-child(even) { background: #FBFAF7; }
tr.total { background: #E8F1EF; font-weight: 700; }
.timestamp {
  float: right;
  font-size: 0.55em;
  font-weight: 400;
  color: #667085;
  background: #E8E0D6;
  padding: 4px 12px;
  border-radius: 8px;
}
.chart-links {
  margin: 12px 0 16px;
  padding: 8px 14px;
  background: #E8F1EF;
  border: 1px solid #B9D2CC;
  border-radius: 8px;
  font-size: 0.9em;
}
.chart-links a { color: #174D47; text-decoration: none; font-weight: 700; margin: 0 4px; }
.empty { color: #667085; }
"""
```

- [ ] **Step 4: Run report tests**

Run:

```powershell
uv run --group dev pytest tests\unit\reporting\test_html_report.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src\scenario_db\reporting\html_report.py tests\unit\reporting\test_html_report.py
git commit -m "feat: generate simulation html report from evidence"
```

---

### Task 5: Local Artifact Bundle Exporter

**Files:**

- Create: `src/scenario_db/reporting/exporter.py`
- Test: `tests/unit/reporting/test_exporter.py`

- [ ] **Step 1: Write failing exporter tests**

Create `tests/unit/reporting/test_exporter.py`:

```python
from __future__ import annotations

from pathlib import Path

from scenario_db.reporting.exporter import generate_report_bundle, write_report_bundle
from scenario_db.reporting.models import ReportContext


def _evidence() -> dict:
    return {
        "id": "sim-1",
        "scenario_ref": "uc-camera-recording",
        "variant_ref": "FHD30-SDR-H265",
        "execution_context": {"silicon_rev": "EVT0", "thermal": "normal"},
        "run_info": {"timestamp": "2026-05-21T01:02:03+09:00", "tool": "scenariodb-sim"},
        "kpi": {"total_power_mw": 1.0, "total_power_ma": 0.25, "core_power_mw": 1.0, "bw_power_mw": 0.0, "total_bw_mbs": 100.0, "hw_time_max_ms": 1.0},
        "timeline_events": [{"task_id": "isp#f0", "node_id": "isp", "hw_name": "ISP", "frame_index": 0, "start_ms": 0.0, "end_ms": 1.0, "duration_ms": 1.0}],
        "dma_breakdown": [{"node_id": "isp", "hw_name": "ISP", "port": "ISP_WDMA", "direction": "write", "bw_mbs": 100.0, "bw_power_mw": 8.0, "bw_power_ma": 2.35}],
        "dvfs_breakdown": [{"node_id": "isp", "hw_name": "ISP", "mode": "Normal", "dvfs_group": "CAM", "set_clock_mhz": 332, "dvfs_level": 4, "set_voltage_mv": 606.25, "vdd": "VDD_CAM"}],
    }


def test_generate_report_bundle_contains_three_html_documents():
    context = ReportContext(evidence_id="sim-1", scenario_ref="uc-camera-recording", variant_ref="FHD30-SDR-H265", project_ref="projectA", variant_name="FHD30 Recording")

    bundle = generate_report_bundle(_evidence(), context=context)

    assert bundle.prefix == "projectA-FHD30_Recording"
    assert "Plotly.newPlot" in bundle.timing_chart_html
    assert "Plotly.newPlot" in bundle.bw_chart_html
    assert "Simulation Report" in bundle.simulation_report_html


def test_write_report_bundle_writes_files_and_returns_artifacts(tmp_path: Path):
    context = ReportContext(evidence_id="sim-1", scenario_ref="uc-camera-recording", variant_ref="FHD30-SDR-H265", project_ref="projectA", variant_name="FHD30 Recording")
    bundle = generate_report_bundle(_evidence(), context=context)

    artifacts = write_report_bundle(bundle, output_dir=tmp_path)

    assert sorted(item.type for item in artifacts) == ["bw_chart", "simulation_report", "timing_chart"]
    for artifact in artifacts:
        assert artifact.storage == "local"
        assert artifact.path.exists()
        assert artifact.sha256
        assert artifact.bytes > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
uv run --group dev pytest tests\unit\reporting\test_exporter.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scenario_db.reporting.exporter'`.

- [ ] **Step 3: Implement bundle generator and writer**

Create `src/scenario_db/reporting/exporter.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from scenario_db.reporting.charts import generate_bw_chart_html, generate_timing_chart_html
from scenario_db.reporting.filenames import artifact_filenames, build_report_prefix
from scenario_db.reporting.html_report import generate_simulation_report_html
from scenario_db.reporting.models import GeneratedReportBundle, ReportContext, WrittenArtifact


def generate_report_bundle(evidence: dict[str, Any], *, context: ReportContext) -> GeneratedReportBundle:
    prefix = build_report_prefix(context)
    names = artifact_filenames(prefix)
    timing_html = generate_timing_chart_html(evidence, title=context.variant_name or context.variant_ref)
    bw_html = generate_bw_chart_html(evidence, title=f"{context.variant_name or context.variant_ref} - Bandwidth Timeline")
    report_html = generate_simulation_report_html(
        evidence,
        context=context,
        timing_chart_file=names.timing_chart,
        bw_chart_file=names.bw_chart,
    )
    return GeneratedReportBundle(
        prefix=prefix,
        timing_chart_html=timing_html,
        bw_chart_html=bw_html,
        simulation_report_html=report_html,
    )


def write_report_bundle(bundle: GeneratedReportBundle, *, output_dir: Path | str) -> list[WrittenArtifact]:
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    names = artifact_filenames(bundle.prefix)
    outputs = [
        ("timing_chart", names.timing_chart, bundle.timing_chart_html),
        ("bw_chart", names.bw_chart, bundle.bw_chart_html),
        ("simulation_report", names.simulation_report, bundle.simulation_report_html),
    ]
    artifacts: list[WrittenArtifact] = []
    for artifact_type, filename, html in outputs:
        if html is None:
            continue
        path = directory / filename
        data = html.encode("utf-8")
        path.write_bytes(data)
        artifacts.append(
            WrittenArtifact(
                type=artifact_type,
                storage="local",
                path=path,
                sha256=hashlib.sha256(data).hexdigest(),
                bytes=len(data),
            )
        )
    return artifacts
```

- [ ] **Step 4: Run exporter tests**

Run:

```powershell
uv run --group dev pytest tests\unit\reporting\test_exporter.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src\scenario_db\reporting\exporter.py tests\unit\reporting\test_exporter.py
git commit -m "feat: write local simulation report html bundle"
```

---

### Task 6: API Export Endpoint And Artifact Persistence

**Files:**

- Modify: `src/scenario_db/api/schemas/simulation.py`
- Modify: `src/scenario_db/api/routers/simulation.py`
- Modify: `src/scenario_db/db/repositories/evidence.py`
- Test: `tests/unit/api/test_simulation.py`

- [ ] **Step 1: Add failing API tests**

Append to `tests/unit/api/test_simulation.py`:

```python
def test_export_simulation_artifacts_endpoint(monkeypatch):
    app = create_app()
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    fake_row = MagicMock()
    fake_row.kind = "evidence.simulation"
    fake_row.id = "sim-1"
    fake_row.scenario_ref = "uc-camera-recording"
    fake_row.variant_ref = "FHD30-SDR-H265"
    fake_row.sw_baseline_ref = "sw-vendor-v1.2.3"
    fake_row.execution_context = {"silicon_rev": "EVT0", "thermal": "normal"}
    fake_row.run_info = {"timestamp": "2026-05-21T01:02:03+09:00", "tool": "scenariodb-sim"}
    fake_row.kpi = {}
    fake_row.ip_breakdown = []
    fake_row.dma_breakdown = []
    fake_row.timing_breakdown = []
    fake_row.dvfs_breakdown = []
    fake_row.timeline_events = []
    fake_row.external_devices = []
    fake_row.topology_order = []
    fake_row.vdd_power = {}
    fake_row.calculation_trace = None
    fake_row.params_hash = "abc123"
    fake_row.artifacts = []

    class _Project:
        id = "projectA"

    class _Variant:
        id = "FHD30-SDR-H265"

    class _Graph:
        project = _Project()
        variant = _Variant()

    monkeypatch.setattr(simulation_router, "get_evidence", lambda db_arg, evidence_id: fake_row)
    monkeypatch.setattr(simulation_router, "load_canonical_graph", lambda db_arg, scenario_id, variant_id: _Graph())
    monkeypatch.setattr(simulation_router, "get_settings", lambda: MagicMock(report_dir="output_simulation"))
    monkeypatch.setattr(
        simulation_router,
        "generate_report_bundle",
        lambda evidence, context: MagicMock(prefix="projectA-FHD30-SDR-H265"),
    )
    monkeypatch.setattr(
        simulation_router,
        "write_report_bundle",
        lambda bundle, output_dir: [
            MagicMock(type="simulation_report", storage="local", path=Path("output_simulation/report.html"), sha256="abc", bytes=123)
        ],
    )
    monkeypatch.setattr(simulation_router, "replace_simulation_artifacts", lambda db_arg, evidence_id, artifacts: fake_row)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/simulation/results/sim-1/artifacts/export", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["evidence_id"] == "sim-1"
    assert body["prefix"] == "projectA-FHD30-SDR-H265"
    assert body["artifacts"][0]["type"] == "simulation_report"
    db.commit.assert_called_once()
```

Add imports at the top of the same file:

```python
from pathlib import Path
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
uv run --group dev pytest tests\unit\api\test_simulation.py::test_export_simulation_artifacts_endpoint -v
```

Expected: FAIL with status `404` because the endpoint does not exist.

- [ ] **Step 3: Add schemas**

Modify `src/scenario_db/api/schemas/simulation.py`:

```python
class SimulationArtifactExportRequest(BaseModel):
    overwrite: bool = True


class SimulationArtifactResponse(BaseModel):
    type: str
    storage: str
    path: str
    sha256: str
    bytes: int


class SimulationArtifactExportResponse(BaseModel):
    evidence_id: str
    prefix: str
    output_dir: str
    artifacts: list[SimulationArtifactResponse] = Field(default_factory=list)
```

- [ ] **Step 4: Add repository helper**

Modify `src/scenario_db/db/repositories/evidence.py`:

```python
def replace_simulation_artifacts(
    db: Session,
    evidence_id: str,
    artifacts: list[dict],
) -> Evidence | None:
    row = db.query(Evidence).filter_by(id=evidence_id).one_or_none()
    if row is None or row.kind != "evidence.simulation":
        return None
    row.artifacts = artifacts
    db.add(row)
    return row
```

- [ ] **Step 5: Add router endpoint**

Modify `src/scenario_db/api/routers/simulation.py` imports:

```python
from pathlib import Path

from scenario_db.config import get_settings
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.reporting.exporter import generate_report_bundle, write_report_bundle
from scenario_db.reporting.models import ReportContext
```

Extend repository imports:

```python
from scenario_db.db.repositories.evidence import (
    delete_simulation_evidence,
    get_evidence,
    list_simulation_results,
    replace_simulation_artifacts,
)
```

Extend schema imports:

```python
from scenario_db.api.schemas.simulation import (
    SimulateRequest,
    SimulateRunResponse,
    SimulationArtifactExportRequest,
    SimulationArtifactExportResponse,
    SimulationReadinessResponse,
)
```

Add endpoint before the delete endpoint:

```python
@router.post("/results/{evidence_id}/artifacts/export", response_model=SimulationArtifactExportResponse)
def export_result_artifacts(
    evidence_id: str,
    request: SimulationArtifactExportRequest,
    db: Session = Depends(get_db),
):
    row = get_evidence(db, evidence_id)
    if row is None or row.kind != "evidence.simulation":
        raise NoResultFound(f"Simulation evidence '{evidence_id}' not found")

    evidence = EvidenceResponse.model_validate(row).model_dump(mode="json")
    project_ref = None
    variant_name = row.variant_ref
    try:
        graph = load_canonical_graph(db, row.scenario_ref, row.variant_ref)
        project_ref = getattr(getattr(graph, "project", None), "id", None)
        variant_name = getattr(getattr(graph, "variant", None), "id", row.variant_ref)
    except Exception:
        project_ref = None

    context = ReportContext(
        evidence_id=row.id,
        scenario_ref=row.scenario_ref,
        variant_ref=row.variant_ref,
        project_ref=project_ref,
        variant_name=variant_name,
    )
    bundle = generate_report_bundle(evidence, context=context)
    output_dir = Path(get_settings().report_dir)
    written = write_report_bundle(bundle, output_dir=output_dir)
    artifact_dicts = [
        {
            "type": item.type,
            "storage": item.storage,
            "path": str(item.path),
            "sha256": item.sha256,
            "bytes": item.bytes,
        }
        for item in written
    ]
    replace_simulation_artifacts(db, evidence_id, artifact_dicts)
    db.commit()
    return SimulationArtifactExportResponse(
        evidence_id=evidence_id,
        prefix=bundle.prefix,
        output_dir=str(output_dir),
        artifacts=artifact_dicts,
    )
```

- [ ] **Step 6: Run focused API tests**

Run:

```powershell
uv run --group dev pytest tests\unit\api\test_simulation.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src\scenario_db\api\schemas\simulation.py src\scenario_db\api\routers\simulation.py src\scenario_db\db\repositories\evidence.py tests\unit\api\test_simulation.py
git commit -m "feat: export simulation html artifacts through api"
```

---

### Task 7: Evidence Dashboard Integration

**Files:**

- Create: `dashboard/components/simulation_report_actions.py`
- Modify: `dashboard/components/simulation_api_client.py`
- Modify: `dashboard/components/evidence_dashboard_contract.py`
- Modify: `dashboard/components/evidence_actions.py`
- Modify: `dashboard/components/evidence_result_view.py`
- Test: `tests/unit/dashboard/test_simulation_report_actions.py`
- Test: `tests/unit/dashboard/test_evidence_dashboard_contract.py`

- [ ] **Step 1: Write failing dashboard action tests**

Create `tests/unit/dashboard/test_simulation_report_actions.py`:

```python
from __future__ import annotations

from dashboard.components.simulation_report_actions import (
    artifact_export_summary_rows,
    report_download_filename,
)


def test_report_download_filename_uses_evidence_id_and_legacy_suffix():
    assert report_download_filename({"id": "sim-uc-camera-recording-FHD30-abc"}) == "sim-uc-camera-recording-FHD30-abc_simulation_result.html"


def test_artifact_export_summary_rows_preserve_path_hash_and_size():
    rows = artifact_export_summary_rows(
        {
            "artifacts": [
                {"type": "simulation_report", "storage": "local", "path": "output_simulation/report.html", "sha256": "abc123", "bytes": 42}
            ]
        }
    )

    assert rows == [
        {
            "type": "simulation_report",
            "storage": "local",
            "path": "output_simulation/report.html",
            "sha256": "abc123",
            "bytes": 42,
        }
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
uv run --group dev --group dashboard pytest tests\unit\dashboard\test_simulation_report_actions.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'dashboard.components.simulation_report_actions'`.

- [ ] **Step 3: Add simulation API client method**

Modify `dashboard/components/simulation_api_client.py`:

```python
def export_simulation_artifacts(
    base_url: str,
    evidence_id: str,
    *,
    overwrite: bool = True,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        base_url,
        f"/simulation/results/{evidence_id}/artifacts/export",
        json={"overwrite": overwrite},
    )
```

- [ ] **Step 4: Add report action helpers**

Create `dashboard/components/simulation_report_actions.py`:

```python
from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.simulation_api_client import export_simulation_artifacts
from dashboard.components.table_actions import render_copyable_dataframe
from dashboard.components.viewer_api_client import ViewerApiError
from scenario_db.reporting.html_report import generate_simulation_report_html
from scenario_db.reporting.models import ReportContext


def render_simulation_report_actions(result: dict[str, Any], *, api_base: str) -> None:
    evidence_id = str(result.get("id") or "simulation-evidence")
    context = ReportContext(
        evidence_id=evidence_id,
        scenario_ref=str(result.get("scenario_ref") or ""),
        variant_ref=str(result.get("variant_ref") or ""),
        variant_name=str(result.get("variant_ref") or evidence_id),
    )
    report_html = generate_simulation_report_html(result, context=context)
    download_col, export_col = st.columns(2)
    download_col.download_button(
        "Download HTML Report",
        data=report_html.encode("utf-8"),
        file_name=report_download_filename(result),
        mime="text/html",
        use_container_width=True,
        key=f"download_html_report_{evidence_id}",
    )
    if export_col.button("Save HTML Bundle Locally", use_container_width=True, key=f"export_html_bundle_{evidence_id}"):
        try:
            response = export_simulation_artifacts(api_base, evidence_id)
            st.success(f"Saved HTML bundle: {response.get('output_dir')}")
            render_copyable_dataframe(
                artifact_export_summary_rows(response),
                key=f"artifact_export_rows_{evidence_id}",
                use_container_width=True,
                hide_index=True,
            )
        except ViewerApiError as exc:
            st.error(str(exc))
            if exc.body:
                st.code(exc.body)


def report_download_filename(result: dict[str, Any]) -> str:
    evidence_id = _safe_filename(str(result.get("id") or "simulation-evidence"))
    return f"{evidence_id}_simulation_result.html"


def artifact_export_summary_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in response.get("artifacts") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "type": item.get("type"),
                "storage": item.get("storage"),
                "path": item.get("path"),
                "sha256": item.get("sha256"),
                "bytes": item.get("bytes"),
            }
        )
    return rows


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ".-" else "_" for ch in value)[:160]
```

- [ ] **Step 5: Add dashboard label contract**

Modify `dashboard/components/evidence_dashboard_contract.py`:

```python
RESULT_BREAKDOWN_TABS = (
    "External Device Info",
    "IP/Node Power",
    "DMA BW",
    "Timing Chart",
    "Timing Table",
    "Timeline Table",
    "Report",
    "Debug Trace",
    "Raw Evidence",
)
```

Keep `SAVED_ACTION_LABELS` as-is for compatibility. The new local export actions live inside the `Report` tab.

- [ ] **Step 6: Wire report tab**

Modify `dashboard/components/evidence_result_view.py` imports:

```python
from dashboard.components.simulation_report_actions import render_simulation_report_actions
```

Change `render_result_breakdown` signature:

```python
def render_result_breakdown(result: dict[str, Any], *, key_prefix: str = "stored", api_base: str | None = None) -> None:
```

Change tab body order:

```python
    with tabs[6]:
        if api_base:
            render_simulation_report_actions(result, api_base=api_base)
        else:
            st.info("Report export requires an API base URL.")
    with tabs[7]:
        render_debug_trace(result)
    with tabs[8]:
        st.json(result)
```

- [ ] **Step 7: Pass API base from result panel**

Modify `dashboard/components/evidence_results_panel.py` calls to `render_result_breakdown`:

```python
render_result_breakdown(preview_result, key_prefix="preview", api_base=api_base)
```

and:

```python
render_result_breakdown(selected, key_prefix="saved", api_base=api_base)
```

- [ ] **Step 8: Run dashboard tests**

Run:

```powershell
uv run --group dev --group dashboard pytest tests\unit\dashboard\test_simulation_report_actions.py tests\unit\dashboard\test_evidence_dashboard_contract.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add dashboard\components\simulation_report_actions.py dashboard\components\simulation_api_client.py dashboard\components\evidence_dashboard_contract.py dashboard\components\evidence_result_view.py dashboard\components\evidence_results_panel.py tests\unit\dashboard\test_simulation_report_actions.py tests\unit\dashboard\test_evidence_dashboard_contract.py
git commit -m "feat: add dashboard simulation html report export"
```

---

### Task 8: End-To-End Verification And Documentation

**Files:**

- Modify: `README.md`
- Modify: `docs/dashboard-regression-checklist.md`
- Test: focused unit suites and optional local API/dashboard smoke.

- [ ] **Step 1: Update README simulation dashboard section**

Modify `README.md` under `Simulation Evidence Dashboard` with:

```markdown
Saved simulation evidence can generate a local HTML report bundle from the
`Report` tab:

- `{prefix}_timing_chart.html`
- `{prefix}_bw_chart.html`
- `{prefix}_simulation_result.html`

The API writes these files under `SCENARIO_DB_REPORT_DIR`, defaulting to
`output_simulation` relative to the API process working directory.

```powershell
$env:SCENARIO_DB_REPORT_DIR="E:\50_Codex_Soc_Scenario_DB\implementation\output_simulation"
```

The browser-side `Download HTML Report` action downloads only the report page.
Use `Save HTML Bundle Locally` to create all three files on the machine running
the API and persist the artifact paths/hashes back into `evidence.artifacts`.
```
```

- [ ] **Step 2: Update dashboard regression checklist**

Modify `docs/dashboard-regression-checklist.md` with:

```markdown
## Simulation Report Artifacts

- Evidence Dashboard -> Saved Evidence -> Report tab is visible.
- `Download HTML Report` downloads a `*_simulation_result.html` file.
- `Save HTML Bundle Locally` writes three files under `SCENARIO_DB_REPORT_DIR`
  or `output_simulation`.
- The generated simulation report links to the generated timing and BW chart
  files by relative filename.
- The API response lists artifact `type`, `storage`, `path`, `sha256`, and
  `bytes`.
- Refreshing the selected evidence shows the same artifact metadata in raw
  evidence JSON.
```

- [ ] **Step 3: Run focused unit tests**

Run:

```powershell
uv run --group dev --group dashboard pytest tests\unit\reporting tests\unit\api\test_simulation.py tests\unit\dashboard\test_simulation_report_actions.py tests\unit\dashboard\test_evidence_dashboard_contract.py -v
```

Expected: PASS.

- [ ] **Step 4: Run simulation unit suite**

Run:

```powershell
uv run --group dev --group sim pytest tests\unit\sim tests\unit\api\test_simulation.py -v
```

Expected: PASS.

- [ ] **Step 5: Manual local smoke with existing services**

Start API:

```powershell
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:15432/scenario_db"
$env:SCENARIO_DB_REPORT_DIR="E:\50_Codex_Soc_Scenario_DB\implementation\output_simulation"
uv run uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
```

Run or reuse saved evidence through the dashboard, then call export directly:

```powershell
$api="http://127.0.0.1:18000/api/v1"
$evidenceId="<saved-evidence-id-from-dashboard>"
Invoke-RestMethod -Method Post -Uri "$api/simulation/results/$evidenceId/artifacts/export" -ContentType "application/json" -Body '{"overwrite":true}' | ConvertTo-Json -Depth 10
Get-ChildItem .\output_simulation\*_timing_chart.html,.\output_simulation\*_bw_chart.html,.\output_simulation\*_simulation_result.html
```

Expected:

- API returns `evidence_id`, `prefix`, `output_dir`, and three artifact rows.
- `output_simulation` contains three HTML files.
- Opening `*_simulation_result.html` shows links to the chart HTML files.
- Opening chart HTML files shows Plotly content, not a blank page.

- [ ] **Step 6: Commit docs**

```powershell
git add README.md docs\dashboard-regression-checklist.md
git commit -m "docs: document simulation html report export"
```

---

## Final Verification Gate

Run before handing off:

```powershell
uv run --group dev --group dashboard pytest tests\unit\reporting tests\unit\dashboard tests\unit\api\test_simulation.py -v
uv run --group dev --group sim pytest tests\unit\sim -v
```

Expected:

- All reporting tests pass.
- Existing dashboard timing/table tests still pass.
- Simulation API tests pass.
- Simulation core tests pass.

If Docker/PostgreSQL is available, also run:

```powershell
uv run --group dev pytest tests\integration\test_api_evidence.py tests\integration\test_runtime_view_e2e.py -v
```

Expected:

- Existing evidence API and runtime view integration behavior is unchanged.

## Risk Notes

- `Evidence` currently persists `artifacts` as JSONB, so no Alembic migration is needed.
- The current DB model does not persist `project_ref` directly on `Evidence`; API export derives it from `load_canonical_graph()` when possible and falls back to `scenario_ref`.
- BW chart timing requires `timeline_events`. If a result was saved with `include_timeline=false`, the BW chart generator returns a clear HTML message instead of failing.
- API-side Plotly export requires `plotly` in base dependencies, not only the dashboard group.
- Browser download and API local save are intentionally separate actions because browser download cannot guarantee a server-local path.

## Self-Review

- Spec coverage: The plan covers chart generation, report generation, local file write, artifact metadata persistence, dashboard integration, API integration, and docs.
- Placeholder scan: No unfinished-marker wording or undefined future phase remains.
- Type consistency: `ReportContext`, `GeneratedReportBundle`, `WrittenArtifact`, and simulation artifact response names are defined before use.
