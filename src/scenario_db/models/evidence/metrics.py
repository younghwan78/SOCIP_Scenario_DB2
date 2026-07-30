from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Literal

import yaml
from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel

MetricStatistic = Literal["value", "mean", "p50", "p95", "p99", "min", "max"]
MetricPolarity = Literal["lower_is_better", "higher_is_better", "neutral"]
_METRIC_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


class MetricScope(BaseScenarioModel):
    kind: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    ref: str = Field(min_length=1)


class MetricStatistics(BaseScenarioModel):
    mean: float | None = None
    p50: float | None = None
    p95: float | None = None
    p99: float | None = None
    min: float | None = None
    max: float | None = None
    std: float | None = None
    n: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _require_statistic(self) -> MetricStatistics:
        values = (self.mean, self.p50, self.p95, self.p99, self.min, self.max, self.std)
        if not any(value is not None for value in values):
            raise ValueError("metric stats require at least one numeric statistic")
        return self


class MetricObservation(BaseScenarioModel):
    metric_id: str = Field(pattern=_METRIC_ID_RE.pattern)
    scope: MetricScope
    unit: str = Field(min_length=1)
    value: float | int | None = None
    stats: MetricStatistics | None = None
    source_artifact_ref: str | None = None

    @model_validator(mode="after")
    def _require_one_value_shape(self) -> MetricObservation:
        if (self.value is None) == (self.stats is None):
            raise ValueError("metric observation requires exactly one of value or stats")
        return self

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.metric_id, self.scope.kind, self.scope.ref)


class MetricDefinition(BaseScenarioModel):
    category: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    canonical_unit: str = Field(min_length=1)
    allowed_scopes: set[str] = Field(min_length=1)
    compare_statistic: MetricStatistic
    polarity: MetricPolarity = "neutral"
    kpi_key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")


class MetricCatalog(BaseScenarioModel):
    version: str
    metrics: dict[str, MetricDefinition]

    @model_validator(mode="after")
    def _validate_metric_ids_and_kpi_keys(self) -> MetricCatalog:
        observation_ids: set[str] = set()
        kpi_keys: set[str] = set()
        for metric_id, definition in self.metrics.items():
            if not _METRIC_ID_RE.fullmatch(metric_id):
                raise ValueError(f"invalid metric id in catalog: {metric_id}")
            if metric_id in observation_ids:
                raise ValueError(f"duplicate metric id in catalog: {metric_id}")
            observation_ids.add(metric_id)
            if definition.kpi_key:
                if definition.kpi_key in kpi_keys:
                    raise ValueError(f"duplicate kpi_key in metric catalog: {definition.kpi_key}")
                kpi_keys.add(definition.kpi_key)
        return self


@lru_cache(maxsize=1)
def load_default_metric_catalog() -> MetricCatalog:
    path = Path(__file__).with_name("metric_catalog.yaml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return MetricCatalog.model_validate(raw)


def validate_metric_observations(
    observations: list[MetricObservation],
    *,
    catalog: MetricCatalog | None = None,
) -> None:
    active_catalog = catalog or load_default_metric_catalog()
    identities: set[tuple[str, str, str]] = set()
    for observation in observations:
        definition = active_catalog.metrics.get(observation.metric_id)
        if definition is None:
            raise ValueError(f"unknown metric_id '{observation.metric_id}'")
        if observation.scope.kind not in definition.allowed_scopes:
            raise ValueError(
                f"metric '{observation.metric_id}' does not allow scope "
                f"'{observation.scope.kind}'"
            )
        if observation.unit != definition.canonical_unit:
            raise ValueError(
                f"metric '{observation.metric_id}' requires unit "
                f"'{definition.canonical_unit}', got '{observation.unit}'"
            )
        if observation.identity in identities:
            raise ValueError(
                "duplicate metric observation for "
                f"{observation.metric_id}/{observation.scope.kind}/{observation.scope.ref}"
            )
        identities.add(observation.identity)
