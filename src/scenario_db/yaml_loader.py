"""Safe YAML parsing with LibYAML acceleration when available.

Both loaders use PyYAML's SafeConstructor; Python object tags remain forbidden.
Keep serialization unchanged so fixture formatting and hashes do not drift.
"""
from __future__ import annotations

from typing import Any

import yaml

_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def safe_load(text: str) -> Any:
    return yaml.load(text, Loader=_SAFE_LOADER)
