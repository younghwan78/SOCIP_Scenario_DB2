from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.simulation_api_client import get_simulation_readiness
from dashboard.components.viewer_api_client import ViewerApiError


def render_simulation_readiness(api_base: str, scenario_id: str, variant_id: str) -> None:
    try:
        report = get_simulation_readiness(api_base, scenario_id=scenario_id, variant_id=variant_id)
    except ViewerApiError as exc:
        st.caption(f"Simulation readiness unavailable: {exc}")
        return

    status = str(report.get("status") or "unknown")
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    errors = _issues(report.get("errors"))
    warnings = _issues(report.get("warnings"))
    label = (
        f"Readiness: {status} | compute={summary.get('compute_nodes', 0)} "
        f"| DMA={summary.get('dma_transfers', 0)} | external={summary.get('external_devices', 0)}"
    )
    if status == "blocked":
        st.error(label)
    elif status == "warning":
        st.warning(label)
    else:
        st.success(label)

    if errors or warnings:
        with st.expander("Simulation readiness details"):
            for issue in [*errors, *warnings]:
                prefix = f"{issue.get('code', 'ISSUE')}"
                node = issue.get("node_id")
                if node:
                    prefix = f"{prefix} / {node}"
                st.write(f"- {prefix}: {issue.get('message', '')}")


def _issues(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]
