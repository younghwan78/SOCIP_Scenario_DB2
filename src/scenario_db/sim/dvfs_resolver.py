from __future__ import annotations

import math
from collections import defaultdict

from scenario_db.sim.clock_ledger import (
    ambiguous_clock_keys,
    build_clock_ledger,
    lookup_clock,
    select_clock_basis,
)
from scenario_db.sim.clock_models import ClockBasis, ConfiguredClock, MeasuredClock, MeasuredVoltageBasis
from scenario_db.sim.constants import REFERENCE_VOLTAGE_MV
from scenario_db.sim.models import DVFSTable, IPWorkload, ResolvedIPConfig
from scenario_db.sim.power_model import PowerModel, resolve_power_model


class DvfsResolver:
    """Resolve required clock, DVFS level, shared clock, and VDD voltage."""

    def __init__(
        self,
        dvfs_tables: dict[str, DVFSTable],
        *,
        asv_group: int = 4,
        power_model: PowerModel | None = None,
        clock_basis: ClockBasis | None = None,
        configured_clocks: dict[str, ConfiguredClock] | None = None,
        measured_clocks: dict[str, MeasuredClock] | None = None,
    ) -> None:
        self.dvfs_tables = dvfs_tables
        self.asv_group = asv_group
        self.power_model = power_model or resolve_power_model(None)
        self.clock_basis: ClockBasis = clock_basis or "calculated"
        self.configured_clocks = configured_clocks or {}
        self.measured_clocks = measured_clocks or {}
        # Fallback / conflict notes from the last resolve(); the runner surfaces them.
        self.warnings: list[str] = []

    def resolve(
        self,
        workloads: list[IPWorkload],
        *,
        dvfs_overrides: dict[str, int] | None = None,
    ) -> dict[str, ResolvedIPConfig]:
        self.warnings = []
        calculated = self._resolve_pass(workloads, dvfs_overrides, {})
        # The calculated pass is always the reference tier; a configured /
        # measured basis re-runs the resolution with those clocks substituted
        # (shared-clock / DVFS / voltage alignment still applies).
        selections = select_clock_basis(
            workloads,
            basis=self.clock_basis,
            configured=self.configured_clocks,
            measured=self.measured_clocks,
            warnings=self.warnings,
        )
        substitutions = {node_id: sel.mhz for node_id, sel in selections.items() if sel.tier_used != "calculated"}
        ambiguous = ambiguous_clock_keys(workloads)
        # A residency-weighted mean clock is not an operating point. With
        # residency, resolve at the dominant (real) level, then blend V^2 over
        # the levels actually visited; without it, a mean is snapped up to a
        # level and flagged, because that over-estimates voltage and power.
        blends: dict[str, MeasuredClock] = {}
        measured_by_node: dict[str, MeasuredClock] = {}
        for workload in workloads:
            selection = selections.get(workload.node_id)
            if selection is None or selection.tier_used != "measured":
                continue
            meas = lookup_clock(self.measured_clocks, workload, ambiguous=ambiguous)
            if meas is None:
                continue
            measured_by_node[workload.node_id] = meas
            if meas.residency and workload.sim_params.dvfs_group not in (dvfs_overrides or {}):
                substitutions[workload.node_id] = meas.dominant_mhz
                blends[workload.node_id] = meas
            elif meas.residency:
                self.warnings.append(f"{workload.node_id}: explicit DVFS override takes precedence over measured residency")
        resolved = (
            self._resolve_pass(workloads, dvfs_overrides, substitutions)
            if substitutions
            else calculated
        )
        voltage_basis: dict[str, MeasuredVoltageBasis] = {}
        if blends:
            minimum_clocks = {
                node_id: substitutions.get(node_id, config.required_clock_mhz)
                for node_id, config in calculated.items()
            }
            voltage_basis.update(self._apply_residency_blend(resolved, blends, minimum_clocks))
            self._align_voltage_by_vdd(resolved)
            self._recalculate_power(resolved)
        for node_id, meas in measured_by_node.items():
            if node_id in voltage_basis:
                continue
            config = resolved[node_id]
            if not meas.residency and config.set_clock_mhz > meas.mhz + 1e-6 and meas.stat in ("weighted_mean", "mean"):
                voltage_basis[node_id] = "snapped_mean"
                self.warnings.append(
                    f"{node_id}: measured {meas.stat} {meas.mhz:.1f}MHz has no level residency and was "
                    f"snapped up to {config.set_clock_mhz:.1f}MHz; voltage/power are over-estimated. "
                    "Import ip_clock_residency or use measured_clock_stat=dominant."
                )
            else:
                voltage_basis[node_id] = "level"
        for workload in workloads:
            config = resolved[workload.node_id]
            meas = blends.get(workload.node_id)
            if meas is not None and meas.residency:
                peak = max(meas.residency)
                table = self.dvfs_tables.get(config.dvfs_group) if config.dvfs_group else None
                maximum = workload.sim_params.max_clock_mhz
                if ((maximum and peak > maximum)
                        or (table and table.levels and table.find_min_level_for_speed(peak, asv_group=self.asv_group) is None)):
                    config.feasible = False
                    config.infeasible_reason = f"measured residency clock {peak:g}MHz exceeds supported clock"
            config.clock_ledger = build_clock_ledger(
                workload,
                calculated=calculated[workload.node_id],
                group_max_mhz=self._group_required_max(workloads, workload),
                basis=self.clock_basis,
                selection=selections.get(workload.node_id),
                configured=self.configured_clocks,
                measured=self.measured_clocks,
                warnings=self.warnings,
                ambiguous=ambiguous,
                measured_voltage_basis=voltage_basis.get(workload.node_id),
            )
        return resolved

    def _resolve_pass(
        self,
        workloads: list[IPWorkload],
        dvfs_overrides: dict[str, int] | None,
        substitutions: dict[str, float],
    ) -> dict[str, ResolvedIPConfig]:
        resolved = {
            workload.node_id: self._initial_config(workload, substitutions.get(workload.node_id))
            for workload in workloads
        }
        self._align_required_clock_by_dvfs_group(resolved)
        self._apply_manual_clocks(resolved, skip=set(substitutions))
        self._apply_dvfs_tables(resolved)
        self._apply_dvfs_overrides(resolved, dvfs_overrides or {})
        self._align_set_clock_by_dvfs_group(resolved)
        self._align_voltage_by_vdd(resolved)
        self._recalculate_power(resolved)
        for workload in workloads:
            config = resolved[workload.node_id]
            maximum = workload.sim_params.max_clock_mhz
            if maximum and max(config.required_clock_mhz, config.set_clock_mhz) > maximum:
                config.feasible = False
                config.infeasible_reason = f"resolved clock exceeds ip max_clock {maximum:g}MHz"
        return resolved

    def _apply_residency_blend(
        self,
        resolved: dict[str, ResolvedIPConfig],
        blends: dict[str, MeasuredClock],
        minimum_clocks: dict[str, float],
    ) -> dict[str, MeasuredVoltageBasis]:
        """Residency-weighted clock and V_eff = sqrt(sum r_i V_i^2) for measured nodes.

        The V1 IP model is P ~ V^2 at fixed work, so time-weighting V^2 over
        the visited levels gives the energy-equivalent voltage exactly.
        Nodes sharing a DVFS group share the clock, so the whole group takes
        the blend of its highest measured clock.
        """
        by_group: dict[str, MeasuredClock] = {}
        for node_id, meas in blends.items():
            group = resolved[node_id].dvfs_group or f"node:{node_id}"
            current = by_group.get(group)
            if current is None or meas.mhz > current.mhz:
                by_group[group] = meas
        applied: dict[str, MeasuredVoltageBasis] = {}
        for group, meas in by_group.items():
            if group.startswith("node:"):
                members, table = [group[len("node:"):]], None
            else:
                members = [node for node, cfg in resolved.items() if cfg.dvfs_group == group]
                table = self.dvfs_tables.get(group)
            residency = meas.residency or {}
            mean_mhz = sum(mhz * share for mhz, share in residency.items())
            # Keep the resolved domain operating point when an unblended peer
            # (including a calculated fallback) needs a higher clock.
            if any(node not in blends and minimum_clocks[node] > mean_mhz for node in members):
                self.warnings.append(f"{group}: measured residency not applied because a shared-clock peer needs a higher clock")
                continue
            v_eff: float | None = None
            if table is not None and table.levels:
                v2 = 0.0
                for mhz, share in residency.items():
                    level = table.find_min_level_for_speed(mhz, asv_group=self.asv_group) or max(
                        table.levels, key=lambda item: item.speed_mhz
                    )
                    v2 += share * table.voltage_for(level, self.asv_group) ** 2
                v_eff = math.sqrt(v2) if v2 > 0 else None
            for node in members:
                config = resolved[node]
                config.set_clock_mhz = mean_mhz
                if v_eff is not None:
                    config.required_voltage_mv = v_eff
                if node in blends:
                    applied[node] = "residency_weighted"
        return applied

    @staticmethod
    def _group_required_max(workloads: list[IPWorkload], workload: IPWorkload) -> float | None:
        """Largest pre-alignment requirement in the workload's DVFS group (None: ungrouped)."""
        group = workload.sim_params.dvfs_group
        if not group:
            return None
        return max(
            (
                max(_base_required_mhz(item), item.clock_correction_mhz)
                for item in workloads
                if item.sim_params.dvfs_group == group
            ),
            default=None,
        )

    def _initial_config(
        self,
        workload: IPWorkload,
        substituted_mhz: float | None = None,
    ) -> ResolvedIPConfig:
        params = workload.sim_params
        required_clock = 0.0
        if workload.pixels > 0 and workload.fps > 0 and params.ppc > 0:
            usable = max(1e-9, 1.0 - workload.sw_margin)
            required_clock = workload.pixels * workload.fps / usable / params.ppc / 1e6
        base_required_clock = required_clock
        if substituted_mhz is not None:
            # configured / measured basis: that clock replaces the calculated
            # requirement (base_required stays the throughput figure).
            required_clock = substituted_mhz
        elif workload.clock_correction_mhz > required_clock:
            required_clock = workload.clock_correction_mhz

        feasible = True
        infeasible_reason: str | None = None
        max_clock = params.max_clock_mhz or 0.0
        if max_clock > 0 and required_clock > max_clock:
            # Catches IPs without a DVFS table, which otherwise pass at any
            # clock with the reference voltage.
            feasible = False
            infeasible_reason = (
                f"required_clock {required_clock:.1f}MHz exceeds "
                f"ip max_clock {max_clock:.1f}MHz"
            )

        return ResolvedIPConfig(
            node_id=workload.node_id,
            instance_index=workload.instance_index,
            ip_ref=workload.ip_ref,
            hw_name=workload.hw_name,
            mode=workload.mode,
            required_clock_mhz=required_clock,
            base_required_clock_mhz=base_required_clock,
            manual_clock_mhz=workload.manual_clock_mhz,
            clock_correction_mhz=workload.clock_correction_mhz,
            clock_correction_reason=workload.clock_correction_reason,
            set_clock_mhz=required_clock,
            dvfs_group=params.dvfs_group,
            required_voltage_mv=0.0,
            set_voltage_mv=0.0,
            vdd=params.vdd,
            width=workload.width,
            height=workload.height,
            format=workload.format,
            unit_power_mw_mp=params.unit_power_mw_mp,
            ppc=params.ppc,
            input_resolution_mp=workload.pixels / 1e6,
            fps=workload.fps,
            active_power_mw=0.0,
            total_power_mw=0.0,
            feasible=feasible,
            infeasible_reason=infeasible_reason,
        )

    def _align_required_clock_by_dvfs_group(
        self,
        resolved: dict[str, ResolvedIPConfig],
    ) -> None:
        for _, node_ids in _group_by(resolved, "dvfs_group").items():
            max_required = max(resolved[node_id].required_clock_mhz for node_id in node_ids)
            for node_id in node_ids:
                resolved[node_id].required_clock_mhz = max_required

    def _apply_manual_clocks(
        self,
        resolved: dict[str, ResolvedIPConfig],
        skip: set[str] | None = None,
    ) -> None:
        for config in resolved.values():
            if skip and config.node_id in skip:
                continue
            manual_clock = config.manual_clock_mhz or 0.0
            if manual_clock > config.required_clock_mhz:
                config.required_clock_mhz = manual_clock

    def _apply_dvfs_tables(self, resolved: dict[str, ResolvedIPConfig]) -> None:
        for config in resolved.values():
            table = self.dvfs_tables.get(config.dvfs_group) if config.dvfs_group else None
            if table is None:
                config.set_clock_mhz = config.required_clock_mhz
                config.required_voltage_mv = getattr(
                    self.power_model, "ref_voltage_mv", REFERENCE_VOLTAGE_MV
                )
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
            max_set = max(resolved[node_id].set_clock_mhz for node_id in node_ids)
            if table is None:
                for node_id in node_ids:
                    resolved[node_id].set_clock_mhz = max_set
                continue
            target_level = table.find_min_level_for_speed(max_set, asv_group=self.asv_group)
            if target_level is None:
                continue
            target_voltage = table.voltage_for(target_level, self.asv_group)
            for node_id in node_ids:
                config = resolved[node_id]
                config.set_clock_mhz = max(config.set_clock_mhz, max_set)
                config.dvfs_level = target_level.level
                # The raised level must carry the raised level's voltage;
                # keeping the pre-alignment voltage under-volts (and therefore
                # under-predicts power for) every node pulled up by the group.
                if target_voltage > 0:
                    config.required_voltage_mv = max(
                        config.required_voltage_mv, target_voltage
                    )

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
            active = self.power_model.ip_active_power_mw(
                unit_power_mw_mp=config.unit_power_mw_mp,
                resolution_mp=config.input_resolution_mp,
                voltage_mv=config.set_voltage_mv,
                fps=config.fps,
            )
            config.active_power_mw = active
            config.total_power_mw = active


def _base_required_mhz(workload: IPWorkload) -> float:
    params = workload.sim_params
    if workload.pixels > 0 and workload.fps > 0 and params.ppc > 0:
        usable = max(1e-9, 1.0 - workload.sw_margin)
        return workload.pixels * workload.fps / usable / params.ppc / 1e6
    return 0.0


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
