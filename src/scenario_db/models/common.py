from __future__ import annotations

from enum import StrEnum
from typing import Annotated, TypeAlias

from pydantic import BaseModel, ConfigDict, StringConstraints

# ---------------------------------------------------------------------------
# Annotated primitive types
# ---------------------------------------------------------------------------

SchemaVersion = Annotated[
    str,
    StringConstraints(pattern=r"^\d+\.\d+(\.\d+)?$"),
]

# Document ID: must start with a known prefix, followed by lowercase alphanum / hyphens / dots
# e.g. ip-isp-v12, sw-vendor-v1.2.3, kernel-6.1.50-android15
DocumentId = Annotated[
    str,
    StringConstraints(
        # Prefix is lowercase; suffix allows mixed-case for acronyms (e.g. iss-LLC-thrashing-0221)
        pattern=(
            r"^(soc|ip|sub|sw|hal|kernel|fw|conn|proj|uc|"
            r"sim|meas|rev|waiver|iss|rule)-[a-zA-Z0-9][a-zA-Z0-9.\-]*$"
        )
    ),
]

# Instance ID: runtime path like ISP.TNR, ISP.3AA0, MFC
InstanceId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z][A-Z0-9]*(\.[A-Z0-9]+)*$"),
]

# feature_flags value: bool, str, or int — no Any
FeatureFlagValue: TypeAlias = bool | str | int


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Severity(StrEnum):
    light = "light"
    medium = "medium"
    heavy = "heavy"
    critical = "critical"


class SourceType(StrEnum):
    calculated = "calculated"
    estimated = "estimated"
    measured = "measured"


class RegressionRisk(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class ViolationAction(StrEnum):
    FAIL_FAST = "FAIL_FAST"
    WARN_AND_CAP = "WARN_AND_CAP"
    WARN_AND_EMULATE = "WARN_AND_EMULATE"
    SKIP_AND_LOG = "SKIP_AND_LOG"
    DEFAULT_TO = "DEFAULT_TO"


class ViolationClassification(StrEnum):
    production = "production"
    exploration = "exploration"
    research = "research"


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------

class BaseScenarioModel(BaseModel):
    """All scenario-db models inherit this to enforce extra='forbid'."""
    model_config = ConfigDict(extra="forbid")
