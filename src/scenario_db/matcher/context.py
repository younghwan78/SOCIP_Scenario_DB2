from __future__ import annotations

from typing import Any


class MatcherContext:
    """
    Normalised view over a variant's JSONB fields for rule evaluation.

    Field accessor prefixes:
        axis.*          → design_conditions
        ip.*            → ip_requirements  (dot-path into nested dict)
        sw_feature.*    → sw_requirements['feature_flags']
        sw_component.*  → sw_requirements['components']
        scope.*         → execution_context
    """

    _PREFIX_MAP: dict[str, tuple[str, ...]] = {
        "axis":         ("design_conditions",),
        "ip":           ("ip_requirements",),
        "sw_feature":   ("sw_requirements", "feature_flags"),
        "sw_component": ("sw_requirements", "components"),
        "scope":        ("execution_context",),
    }

    def __init__(
        self,
        design_conditions: dict | None = None,
        ip_requirements: dict | None = None,
        sw_requirements: dict | None = None,
        execution_context: dict | None = None,
    ) -> None:
        self._data: dict[str, dict] = {
            "design_conditions": design_conditions or {},
            "ip_requirements":   ip_requirements or {},
            "sw_requirements":   sw_requirements or {},
            "execution_context": execution_context or {},
        }

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_variant(cls, variant: Any) -> "MatcherContext":
        """Build context from a ScenarioVariant ORM row."""
        return cls(
            design_conditions=variant.design_conditions,
            ip_requirements=variant.ip_requirements,
            sw_requirements=variant.sw_requirements,
        )

    @classmethod
    def from_evidence(cls, evidence: Any) -> "MatcherContext":
        """Build context from an Evidence ORM row (includes execution_context)."""
        variant = getattr(evidence, "variant", None)
        return cls(
            design_conditions=variant.design_conditions if variant else None,
            ip_requirements=variant.ip_requirements if variant else None,
            sw_requirements=variant.sw_requirements if variant else None,
            execution_context=evidence.execution_context,
        )

    # ------------------------------------------------------------------
    # Field accessor
    # ------------------------------------------------------------------

    def get(self, path: str) -> Any:
        """
        Resolve a dot-separated field path to a value.

        Examples:
            'axis.resolution'           → design_conditions['resolution']
            'ip.ISP.TNR.strength'       → ip_requirements['ISP']['TNR']['strength']
            'sw_feature.LLC_per_ip_partition'
                                        → sw_requirements['feature_flags']['LLC_per_ip_partition']
            'sw_component.kernel'       → sw_requirements['components']['kernel']
            'scope.phase'               → execution_context['phase']
        """
        parts = path.split(".")
        prefix = parts[0]
        if prefix not in self._PREFIX_MAP:
            raise KeyError(f"Unknown context prefix: {prefix!r}. Valid: {list(self._PREFIX_MAP)}")

        root_keys = self._PREFIX_MAP[prefix]
        obj: Any = self._data.get(root_keys[0]) or {}
        for sub_key in root_keys[1:]:
            if not isinstance(obj, dict):
                return None
            obj = obj.get(sub_key)

        for key in parts[1:]:
            if not isinstance(obj, dict):
                return None
            obj = obj.get(key)

        return obj
