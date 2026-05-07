from __future__ import annotations

from collections import defaultdict

from scenario_db.sim.constants import REFERENCE_VOLTAGE_MV
from scenario_db.sim.models import DVFSTable, IPWorkload, ResolvedIPConfig
from scenario_db.sim.power_calc import calc_active_power_mw


class DvfsResolver:
    """Resolve required clock, DVFS level, shared clock, and VDD voltage."""

    def __init__(
        self,
        dvfs_tables: dict[str, DVFSTable],
        *,
        asv_group: int = 4,
    ) -> None:
        self.dvfs_tables = dvfs_tables
        self.asv_group = asv_group

    def resolve(
        self,
        workloads: list[IPWorkload],
        *,
        dvfs_overrides: dict[str, int] | None = None,
    ) -> dict[str, ResolvedIPConfig]:
        resolved = {
            workload.node_id: self._initial_config(workload)
            for workload in workloads
        }
        self._align_required_clock_by_dvfs_group(resolved)
        self._apply_dvfs_tables(resolved)
        self._apply_dvfs_overrides(resolved, dvfs_overrides or {})
        self._align_set_clock_by_dvfs_group(resolved)
        self._align_voltage_by_vdd(resolved)
        self._recalculate_power(resolved)
        return resolved

    def _initial_config(self, workload: IPWorkload) -> ResolvedIPConfig:
        params = workload.sim_params
        required_clock = 0.0
        if workload.pixels > 0 and workload.fps > 0 and params.ppc > 0:
            usable = max(1e-9, 1.0 - workload.sw_margin)
            required_clock = workload.pixels * workload.fps / usable / params.ppc / 1e6
        if workload.manual_clock_mhz and workload.manual_clock_mhz > required_clock:
            required_clock = workload.manual_clock_mhz

        return ResolvedIPConfig(
            node_id=workload.node_id,
            ip_ref=workload.ip_ref,
            hw_name=workload.hw_name,
            mode=workload.mode,
            required_clock_mhz=required_clock,
            set_clock_mhz=required_clock,
            dvfs_group=params.dvfs_group,
            required_voltage_mv=0.0,
            set_voltage_mv=0.0,
            vdd=params.vdd,
            unit_power_mw_mp=params.unit_power_mw_mp,
            ppc=params.ppc,
            input_resolution_mp=workload.pixels / 1e6,
            fps=workload.fps,
            active_power_mw=0.0,
            total_power_mw=0.0,
        )

    def _align_required_clock_by_dvfs_group(
        self,
        resolved: dict[str, ResolvedIPConfig],
    ) -> None:
        for _, node_ids in _group_by(resolved, "dvfs_group").items():
            max_required = max(resolved[node_id].required_clock_mhz for node_id in node_ids)
            for node_id in node_ids:
                resolved[node_id].required_clock_mhz = max_required

    def _apply_dvfs_tables(self, resolved: dict[str, ResolvedIPConfig]) -> None:
        for config in resolved.values():
            if not config.dvfs_group:
                continue
            table = self.dvfs_tables.get(config.dvfs_group)
            if table is None:
                config.required_voltage_mv = REFERENCE_VOLTAGE_MV
                continue
            level = table.find_min_level_for_speed(
                config.required_clock_mhz,
                asv_group=self.asv_group,
            )
            if level is None and table.levels:
                level = max(table.levels, key=lambda item: item.speed_mhz)
                config.feasible = False
                config.infeasible_reason = (
                    f"required_clock {config.required_clock_mhz:.1f}MHz exceeds "
                    f"max DVFS speed {level.speed_mhz:.1f}MHz"
                )
            if level is None:
                continue
            config.set_clock_mhz = level.speed_mhz
            config.dvfs_level = level.level
            config.required_voltage_mv = table.voltage_for(level, self.asv_group)

    def _apply_dvfs_overrides(
        self,
        resolved: dict[str, ResolvedIPConfig],
        overrides: dict[str, int],
    ) -> None:
        for config in resolved.values():
            if not config.dvfs_group or config.dvfs_group not in overrides:
                continue
            table = self.dvfs_tables.get(config.dvfs_group)
            level = table.get_level(overrides[config.dvfs_group]) if table else None
            if level is None:
                config.feasible = False
                config.infeasible_reason = f"DVFS override level not found: {config.dvfs_group}"
                continue
            config.set_clock_mhz = level.speed_mhz
            config.dvfs_level = level.level
            config.required_voltage_mv = table.voltage_for(level, self.asv_group)
            if config.set_clock_mhz < config.required_clock_mhz:
                config.feasible = False
                config.infeasible_reason = (
                    f"set_clock {config.set_clock_mhz:.1f}MHz < "
                    f"required_clock {config.required_clock_mhz:.1f}MHz"
                )

    def _align_set_clock_by_dvfs_group(
        self,
        resolved: dict[str, ResolvedIPConfig],
    ) -> None:
        for group, node_ids in _group_by(resolved, "dvfs_group").items():
            table = self.dvfs_tables.get(group)
            if table is None:
                continue
            max_set = max(resolved[node_id].set_clock_mhz for node_id in node_ids)
            target_level = table.find_min_level_for_speed(max_set, asv_group=self.asv_group)
            if target_level is None:
                continue
            target_voltage = table.voltage_for(target_level, self.asv_group)
            for node_id in node_ids:
                config = resolved[node_id]
                config.set_clock_mhz = max(config.set_clock_mhz, max_set)
                config.dvfs_level = target_level.level
                config.required_voltage_mv = max(config.required_voltage_mv, target_voltage)

    def _align_voltage_by_vdd(self, resolved: dict[str, ResolvedIPConfig]) -> None:
        for _, node_ids in _group_by(resolved, "vdd").items():
            max_voltage = max(resolved[node_id].required_voltage_mv for node_id in node_ids)
            leaders = sorted(
                node_id
                for node_id in node_ids
                if resolved[node_id].required_voltage_mv == max_voltage
            )
            leader = ",".join(leaders)
            for node_id in node_ids:
                resolved[node_id].set_voltage_mv = max_voltage
                resolved[node_id].vdd_leader = leader
        for config in resolved.values():
            if not config.vdd:
                config.set_voltage_mv = config.required_voltage_mv
                config.vdd_leader = config.node_id

    def _recalculate_power(self, resolved: dict[str, ResolvedIPConfig]) -> None:
        for config in resolved.values():
            active = calc_active_power_mw(
                unit_power_mw_mp=config.unit_power_mw_mp,
                resolution_mp=config.input_resolution_mp,
                voltage_mv=config.set_voltage_mv,
                fps=config.fps,
            )
            config.active_power_mw = active
            config.total_power_mw = active


def _group_by(
    resolved: dict[str, ResolvedIPConfig],
    field: str,
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for node_id, config in resolved.items():
        key = getattr(config, field)
        if key:
            groups[str(key)].append(node_id)
    return groups
